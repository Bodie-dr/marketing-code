from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import mimetypes
import random
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional
from uuid import uuid4

import numpy as np
from PIL import Image, ImageEnhance, ImageOps
from skimage.exposure import match_histograms
from tqdm import tqdm

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, Dataset
from torchvision.models import VGG16_Weights, vgg16
from torchvision.transforms import functional as TF
from torchvision.utils import make_grid, save_image

from config import REFERENCE_PHOTOS_FOLDER
from database import create_connection


SUPPORTED_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".bmp",
    ".tif",
    ".tiff",
}

REFERENCE_PHOTOS_DIR = REFERENCE_PHOTOS_FOLDER

logger = logging.getLogger(__name__)


def ensure_photo_references_table(connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS photo_references (
                id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                content_type TEXT NOT NULL,
                checksum_sha256 TEXT NOT NULL UNIQUE,
                image_data BLOB NOT NULL,
                created_at TEXT NOT NULL DEFAULT (NOW()),
                updated_at TEXT NOT NULL DEFAULT (NOW())
            )
            """
        )
    connection.commit()


def ensure_training_photo_pairs_table(connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS training_photo_pairs (
                id TEXT PRIMARY KEY,
                split TEXT NOT NULL
                    CHECK (split IN ('train', 'val')),
                input_filename TEXT NOT NULL,
                target_filename TEXT NOT NULL,
                input_image BLOB NOT NULL,
                target_image BLOB NOT NULL,
                created_at TEXT NOT NULL DEFAULT (NOW()),
                updated_at TEXT NOT NULL DEFAULT (NOW()),
                CONSTRAINT unique_training_photo_pair
                    UNIQUE(split, input_filename, target_filename)
            )
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_training_photo_pairs_split
            ON training_photo_pairs(split)
            """
        )
    connection.commit()


def import_local_training_pairs(
    connection,
    split: str,
    input_dir: str | Path,
    target_dir: str | Path,
) -> int:
    input_dir = Path(input_dir)
    target_dir = Path(target_dir)

    if not input_dir.exists() or not target_dir.exists():
        raise FileNotFoundError(
            f"Trainingsdata niet gevonden: {input_dir} / {target_dir}"
        )

    imported = 0

    with connection.cursor() as cursor:
        for input_path in sorted(input_dir.iterdir()):
            if not input_path.is_file():
                continue

            if input_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue

            target_path = target_dir / input_path.name
            if not target_path.exists():
                continue

            input_bytes = input_path.read_bytes()
            target_bytes = target_path.read_bytes()

            cursor.execute(
                """
                INSERT INTO training_photo_pairs (
                    id,
                    split,
                    input_filename,
                    target_filename,
                    input_image,
                    target_image
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (split, input_filename, target_filename)
                DO UPDATE SET
                    input_image = EXCLUDED.input_image,
                    target_image = EXCLUDED.target_image,
                    updated_at = NOW()
                """,
                (
                    uuid4(),
                    split,
                    input_path.name,
                    target_path.name,
                    input_bytes,
                    target_bytes,
                ),
            )
            imported += 1

    connection.commit()
    return imported


@dataclass
class Config:
    train_input_dir: str = "data/train/input"
    train_target_dir: str = "data/train/target"
    val_input_dir: str = "data/val/input"
    val_target_dir: str = "data/val/target"

    output_dir: str = "outputs"
    checkpoint_path: str = "outputs/best_model.pt"

    image_size: int = 512
    batch_size: int = 2
    epochs: int = 60
    learning_rate: float = 2e-4
    num_workers: int = 0
    seed: int = 42

    base_channels: int = 32
    residual_strength: float = 0.35

    l1_weight: float = 1.0
    perceptual_weight: float = 0.08
    exposure_weight: float = 0.35
    highlight_weight: float = 0.25
    color_weight: float = 0.15
    gradient_weight: float = 0.10
    total_variation_weight: float = 0.00005

    max_highlight_value: float = 0.94
    exposure_tolerance: float = 0.025
    max_gradient_norm: float = 1.0
    early_stopping_patience: int = 12


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)

    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def get_device() -> torch.device:
    if torch.cuda.is_available():
        return torch.device("cuda")

    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return torch.device("mps")

    return torch.device("cpu")


def open_rgb_image(path: Path) -> Image.Image:
    with Image.open(path) as image:
        image = ImageOps.exif_transpose(image)
        return image.convert("RGB")


def resize_and_center_crop(
    image: Image.Image,
    size: int,
) -> Image.Image:
    width, height = image.size

    scale = size / min(width, height)
    new_width = max(size, round(width * scale))
    new_height = max(size, round(height * scale))

    image = image.resize(
        (new_width, new_height),
        Image.Resampling.LANCZOS,
    )

    left = (new_width - size) // 2
    top = (new_height - size) // 2

    return image.crop(
        (
            left,
            top,
            left + size,
            top + size,
        )
    )


def paired_random_crop(
    input_image: Image.Image,
    target_image: Image.Image,
    size: int,
) -> tuple[Image.Image, Image.Image]:
    input_width, input_height = input_image.size
    target_width, target_height = target_image.size

    if (input_width, input_height) != (target_width, target_height):
        target_image = target_image.resize(
            (input_width, input_height),
            Image.Resampling.LANCZOS,
        )

    if input_width < size or input_height < size:
        scale = size / min(input_width, input_height)

        new_width = max(size, round(input_width * scale))
        new_height = max(size, round(input_height * scale))

        input_image = input_image.resize(
            (new_width, new_height),
            Image.Resampling.LANCZOS,
        )
        target_image = target_image.resize(
            (new_width, new_height),
            Image.Resampling.LANCZOS,
        )

        input_width, input_height = input_image.size

    left = random.randint(0, input_width - size)
    top = random.randint(0, input_height - size)

    crop_box = (
        left,
        top,
        left + size,
        top + size,
    )

    return (
        input_image.crop(crop_box),
        target_image.crop(crop_box),
    )


class PairedPhotoDataset(Dataset):
    def __init__(
        self,
        input_dir: str | Path,
        target_dir: str | Path,
        image_size: int,
        training: bool,
    ) -> None:
        self.input_dir = Path(input_dir)
        self.target_dir = Path(target_dir)
        self.image_size = image_size
        self.training = training

        if not self.input_dir.exists():
            raise FileNotFoundError(
                f"Inputmap bestaat niet: {self.input_dir}"
            )

        if not self.target_dir.exists():
            raise FileNotFoundError(
                f"Targetmap bestaat niet: {self.target_dir}"
            )

        self.pairs: list[tuple[Path, Path]] = []

        for input_path in sorted(self.input_dir.iterdir()):
            if (
                input_path.is_file()
                and input_path.suffix.lower() in SUPPORTED_EXTENSIONS
            ):
                target_path = self.target_dir / input_path.name

                if target_path.exists():
                    self.pairs.append((input_path, target_path))
                else:
                    print(
                        f"Waarschuwing: geen target gevonden voor "
                        f"{input_path.name}"
                    )

        if not self.pairs:
            raise RuntimeError(
                "Geen geldige input-targetparen gevonden. "
                "Controleer de mappen en bestandsnamen."
            )

    def __len__(self) -> int:
        return len(self.pairs)

    def __getitem__(
        self,
        index: int,
    ) -> tuple[torch.Tensor, torch.Tensor, str]:
        input_path, target_path = self.pairs[index]

        input_image = open_rgb_image(input_path)
        target_image = open_rgb_image(target_path)

        if input_image.size != target_image.size:
            target_image = target_image.resize(
                input_image.size,
                Image.Resampling.LANCZOS,
            )

        if self.training:
            input_image, target_image = paired_random_crop(
                input_image,
                target_image,
                self.image_size,
            )

            if random.random() < 0.5:
                input_image = TF.hflip(input_image)
                target_image = TF.hflip(target_image)

            if random.random() < 0.15:
                input_image = TF.vflip(input_image)
                target_image = TF.vflip(target_image)

            # Alleen zeer lichte gezamenlijke kleuraanpassing.
            # Geen losse exposure-augmentatie op input of target,
            # omdat het model dan overbelichting kan gaan aanleren.
            if random.random() < 0.25:
                color_factor = random.uniform(0.97, 1.03)

                input_image = ImageEnhance.Color(
                    input_image
                ).enhance(color_factor)

                target_image = ImageEnhance.Color(
                    target_image
                ).enhance(color_factor)

        else:
            input_image = resize_and_center_crop(
                input_image,
                self.image_size,
            )
            target_image = resize_and_center_crop(
                target_image,
                self.image_size,
            )

        input_tensor = TF.to_tensor(input_image)
        target_tensor = TF.to_tensor(target_image)

        return input_tensor, target_tensor, input_path.name


class DatabasePairedPhotoDataset(Dataset):
    def __init__(
        self,
        connection,
        split: str,
        image_size: int,
        training: bool,
    ) -> None:
        self.connection = connection
        self.split = split
        self.image_size = image_size
        self.training = training

        self.pairs: list[tuple[str, bytes, bytes]] = []
        self._load_pairs()

    def _load_pairs(self) -> None:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT input_filename, input_image, target_image
                FROM training_photo_pairs
                WHERE split = %s
                ORDER BY created_at, input_filename
                """,
                (self.split,),
            )
            self.pairs = cursor.fetchall()

        if not self.pairs:
            raise RuntimeError(
                "Geen trainingsdata gevonden in SQLite voor split "
                f"'{self.split}'. Importeer eerst de data naar "
                "training_photo_pairs."
            )

    def __len__(self) -> int:
        return len(self.pairs)

    def __getitem__(
        self,
        index: int,
    ) -> tuple[torch.Tensor, torch.Tensor, str]:
        input_name, input_bytes, target_bytes = self.pairs[index]

        input_image = Image.open(io.BytesIO(input_bytes)).convert("RGB")
        target_image = Image.open(io.BytesIO(target_bytes)).convert("RGB")

        if input_image.size != target_image.size:
            target_image = target_image.resize(
                input_image.size,
                Image.Resampling.LANCZOS,
            )

        if self.training:
            input_image, target_image = paired_random_crop(
                input_image,
                target_image,
                self.image_size,
            )

            if random.random() < 0.5:
                input_image = TF.hflip(input_image)
                target_image = TF.hflip(target_image)

            if random.random() < 0.15:
                input_image = TF.vflip(input_image)
                target_image = TF.vflip(target_image)

            if random.random() < 0.25:
                color_factor = random.uniform(0.97, 1.03)
                input_image = ImageEnhance.Color(
                    input_image
                ).enhance(color_factor)
                target_image = ImageEnhance.Color(
                    target_image
                ).enhance(color_factor)
        else:
            input_image = resize_and_center_crop(
                input_image,
                self.image_size,
            )
            target_image = resize_and_center_crop(
                target_image,
                self.image_size,
            )

        input_tensor = TF.to_tensor(input_image)
        target_tensor = TF.to_tensor(target_image)

        return input_tensor, target_tensor, input_name


class ConvBlock(nn.Module):
    def __init__(
        self,
        in_channels: int,
        out_channels: int,
    ) -> None:
        super().__init__()

        groups = min(8, out_channels)

        while out_channels % groups != 0 and groups > 1:
            groups -= 1

        self.block = nn.Sequential(
            nn.Conv2d(
                in_channels,
                out_channels,
                kernel_size=3,
                padding=1,
                bias=False,
            ),
            nn.GroupNorm(groups, out_channels),
            nn.SiLU(inplace=True),
            nn.Conv2d(
                out_channels,
                out_channels,
                kernel_size=3,
                padding=1,
                bias=False,
            ),
            nn.GroupNorm(groups, out_channels),
            nn.SiLU(inplace=True),
        )

        if in_channels == out_channels:
            self.skip = nn.Identity()
        else:
            self.skip = nn.Conv2d(
                in_channels,
                out_channels,
                kernel_size=1,
            )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.block(x) + self.skip(x)


class DownBlock(nn.Module):
    def __init__(
        self,
        in_channels: int,
        out_channels: int,
    ) -> None:
        super().__init__()

        self.downsample = nn.Conv2d(
            in_channels,
            out_channels,
            kernel_size=4,
            stride=2,
            padding=1,
        )

        self.conv = ConvBlock(
            out_channels,
            out_channels,
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.conv(self.downsample(x))


class UpBlock(nn.Module):
    def __init__(
        self,
        in_channels: int,
        skip_channels: int,
        out_channels: int,
    ) -> None:
        super().__init__()

        self.conv = ConvBlock(
            in_channels + skip_channels,
            out_channels,
        )

    def forward(
        self,
        x: torch.Tensor,
        skip: torch.Tensor,
    ) -> torch.Tensor:
        x = F.interpolate(
            x,
            size=skip.shape[-2:],
            mode="bilinear",
            align_corners=False,
        )

        x = torch.cat([x, skip], dim=1)
        return self.conv(x)


class NaturalPhotoUNet(nn.Module):
    """
    Het model voorspelt geen volledig nieuwe foto.

    Het voorspelt alleen een begrensde residualcorrectie die bij
    de invoer wordt opgeteld. Hierdoor blijft de oorspronkelijke
    foto beter behouden en wordt het risico op een neppe look kleiner.
    """

    def __init__(
        self,
        base_channels: int = 32,
        residual_strength: float = 0.35,
    ) -> None:
        super().__init__()

        b = base_channels
        self.residual_strength = residual_strength

        self.input_block = ConvBlock(3, b)
        self.down1 = DownBlock(b, b * 2)
        self.down2 = DownBlock(b * 2, b * 4)
        self.down3 = DownBlock(b * 4, b * 8)
        self.down4 = DownBlock(b * 8, b * 8)

        self.bottleneck = nn.Sequential(
            ConvBlock(b * 8, b * 8),
            nn.Dropout2d(p=0.05),
            ConvBlock(b * 8, b * 8),
        )

        self.up4 = UpBlock(b * 8, b * 8, b * 8)
        self.up3 = UpBlock(b * 8, b * 8, b * 4)
        self.up2 = UpBlock(b * 4, b * 4, b * 2)
        self.up1 = UpBlock(b * 2, b * 2, b)

        self.output_layer = nn.Sequential(
            nn.Conv2d(
                b,
                b,
                kernel_size=3,
                padding=1,
            ),
            nn.SiLU(inplace=True),
            nn.Conv2d(
                b,
                3,
                kernel_size=1,
            ),
            nn.Tanh(),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x0 = self.input_block(x)
        x1 = self.down1(x0)
        x2 = self.down2(x1)
        x3 = self.down3(x2)
        x4 = self.down4(x3)

        bottleneck = self.bottleneck(x4)

        y = self.up4(bottleneck, x4)
        y = self.up3(y, x3)
        y = self.up2(y, x2)
        y = self.up1(y, x1)

        y = F.interpolate(
            y,
            size=x.shape[-2:],
            mode="bilinear",
            align_corners=False,
        )

        residual = self.output_layer(y)

        output = x + residual * self.residual_strength
        return torch.clamp(output, 0.0, 1.0)


class VGGPerceptualLoss(nn.Module):
    def __init__(self) -> None:
        super().__init__()

        try:
            full_vgg = vgg16(
                weights=VGG16_Weights.DEFAULT
            ).features
        except Exception as error:
            raise RuntimeError(
                "VGG16-gewichten konden niet worden geladen. "
                "De eerste uitvoering heeft internetverbinding nodig "
                "om de vooraf getrainde gewichten te downloaden."
            ) from error

        self.blocks = nn.ModuleList(
            [
                full_vgg[:4].eval(),
                full_vgg[4:9].eval(),
                full_vgg[9:16].eval(),
            ]
        )

        for block in self.blocks:
            for parameter in block.parameters():
                parameter.requires_grad = False

        self.register_buffer(
            "mean",
            torch.tensor(
                [0.485, 0.456, 0.406]
            ).view(1, 3, 1, 1),
        )

        self.register_buffer(
            "std",
            torch.tensor(
                [0.229, 0.224, 0.225]
            ).view(1, 3, 1, 1),
        )

    def normalize(self, image: torch.Tensor) -> torch.Tensor:
        return (image - self.mean) / self.std

    def forward(
        self,
        prediction: torch.Tensor,
        target: torch.Tensor,
    ) -> torch.Tensor:
        prediction_features = self.normalize(prediction)
        target_features = self.normalize(target)

        loss = prediction.new_tensor(0.0)

        for block in self.blocks:
            prediction_features = block(prediction_features)
            target_features = block(target_features)

            loss = loss + F.l1_loss(
                prediction_features,
                target_features.detach(),
            )

        return loss / len(self.blocks)


def rgb_to_luminance(image: torch.Tensor) -> torch.Tensor:
    red = image[:, 0:1]
    green = image[:, 1:2]
    blue = image[:, 2:3]

    return (
        0.2126 * red
        + 0.7152 * green
        + 0.0722 * blue
    )


def exposure_loss(
    prediction: torch.Tensor,
    target: torch.Tensor,
    tolerance: float,
) -> torch.Tensor:
    """
    Vergelijkt lokale gemiddelde helderheid in plaats van alleen
    het gemiddelde van de volledige batch.
    """

    prediction_luminance = rgb_to_luminance(prediction)
    target_luminance = rgb_to_luminance(target)

    prediction_local = F.avg_pool2d(
        prediction_luminance,
        kernel_size=16,
        stride=16,
    )

    target_local = F.avg_pool2d(
        target_luminance,
        kernel_size=16,
        stride=16,
    )

    difference = torch.abs(
        prediction_local - target_local
    )

    return torch.relu(difference - tolerance).mean()


def highlight_loss(
    prediction: torch.Tensor,
    target: torch.Tensor,
    max_highlight_value: float,
) -> torch.Tensor:
    """
    Straft nieuwe, uitgebleekte gebieden extra hard af.

    Een lichte pixel wordt alleen hard bestraft wanneer de target
    op diezelfde plek niet zo licht hoort te zijn.
    """

    prediction_luminance = rgb_to_luminance(prediction)
    target_luminance = rgb_to_luminance(target)

    excessive_highlights = torch.relu(
        prediction_luminance - max_highlight_value
    )

    allowed_highlights = torch.relu(
        target_luminance - max_highlight_value
    )

    new_clipping = torch.relu(
        excessive_highlights - allowed_highlights
    )

    return (
        new_clipping.mean()
        + 0.5 * new_clipping.square().mean()
    )


def color_statistics_loss(
    prediction: torch.Tensor,
    target: torch.Tensor,
) -> torch.Tensor:
    prediction_mean = prediction.mean(
        dim=(2, 3),
        keepdim=True,
    )

    target_mean = target.mean(
        dim=(2, 3),
        keepdim=True,
    )

    prediction_std = prediction.std(
        dim=(2, 3),
        keepdim=True,
    )

    target_std = target.std(
        dim=(2, 3),
        keepdim=True,
    )

    mean_loss = F.l1_loss(
        prediction_mean,
        target_mean,
    )

    std_loss = F.l1_loss(
        prediction_std,
        target_std,
    )

    return mean_loss + std_loss


def image_gradients(
    image: torch.Tensor,
) -> tuple[torch.Tensor, torch.Tensor]:
    gradient_x = image[:, :, :, 1:] - image[:, :, :, :-1]
    gradient_y = image[:, :, 1:, :] - image[:, :, :-1, :]

    return gradient_x, gradient_y


def gradient_loss(
    prediction: torch.Tensor,
    target: torch.Tensor,
) -> torch.Tensor:
    prediction_x, prediction_y = image_gradients(prediction)
    target_x, target_y = image_gradients(target)

    return (
        F.l1_loss(prediction_x, target_x)
        + F.l1_loss(prediction_y, target_y)
    )


def total_variation_loss(image: torch.Tensor) -> torch.Tensor:
    gradient_x, gradient_y = image_gradients(image)

    return (
        gradient_x.abs().mean()
        + gradient_y.abs().mean()
    )


class CombinedNaturalLoss(nn.Module):
    def __init__(
        self,
        config: Config,
        device: torch.device,
    ) -> None:
        super().__init__()

        self.config = config
        self.perceptual = VGGPerceptualLoss().to(device)
        self.perceptual.eval()

    def forward(
        self,
        prediction: torch.Tensor,
        target: torch.Tensor,
    ) -> tuple[torch.Tensor, dict[str, float]]:
        l1 = F.l1_loss(prediction, target)

        perceptual = self.perceptual(
            prediction,
            target,
        )

        exposure = exposure_loss(
            prediction,
            target,
            self.config.exposure_tolerance,
        )

        highlights = highlight_loss(
            prediction,
            target,
            self.config.max_highlight_value,
        )

        colors = color_statistics_loss(
            prediction,
            target,
        )

        gradients = gradient_loss(
            prediction,
            target,
        )

        variation = total_variation_loss(prediction)

        total = (
            self.config.l1_weight * l1
            + self.config.perceptual_weight * perceptual
            + self.config.exposure_weight * exposure
            + self.config.highlight_weight * highlights
            + self.config.color_weight * colors
            + self.config.gradient_weight * gradients
            + self.config.total_variation_weight * variation
        )

        components = {
            "total": float(total.detach().item()),
            "l1": float(l1.detach().item()),
            "perceptual": float(perceptual.detach().item()),
            "exposure": float(exposure.detach().item()),
            "highlights": float(highlights.detach().item()),
            "colors": float(colors.detach().item()),
            "gradients": float(gradients.detach().item()),
            "variation": float(variation.detach().item()),
        }

        return total, components


def calculate_psnr(
    prediction: torch.Tensor,
    target: torch.Tensor,
) -> float:
    mse = F.mse_loss(prediction, target).item()

    if mse == 0:
        return float("inf")

    return 10.0 * np.log10(1.0 / mse)


def save_checkpoint(
    checkpoint_path: Path,
    model: nn.Module,
    optimizer: torch.optim.Optimizer,
    scheduler,
    epoch: int,
    best_val_loss: float,
    config: Config,
) -> None:
    checkpoint_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    torch.save(
        {
            "epoch": epoch,
            "best_val_loss": best_val_loss,
            "model_state_dict": model.state_dict(),
            "optimizer_state_dict": optimizer.state_dict(),
            "scheduler_state_dict": scheduler.state_dict(),
            "config": asdict(config),
        },
        checkpoint_path,
    )


def load_model_from_checkpoint(
    checkpoint_path: str | Path,
    device: torch.device,
) -> tuple[NaturalPhotoUNet, Config]:
    checkpoint_path = Path(checkpoint_path)

    if not checkpoint_path.exists():
        raise FileNotFoundError(
            f"Checkpoint bestaat niet: {checkpoint_path}"
        )

    checkpoint = torch.load(
        checkpoint_path,
        map_location=device,
        weights_only=False,
    )

    saved_config = checkpoint.get("config", {})
    config = Config(**saved_config)

    model = NaturalPhotoUNet(
        base_channels=config.base_channels,
        residual_strength=config.residual_strength,
    ).to(device)

    model.load_state_dict(
        checkpoint["model_state_dict"]
    )

    model.eval()

    return model, config


def run_validation(
    model: nn.Module,
    loader: DataLoader,
    criterion: CombinedNaturalLoss,
    device: torch.device,
) -> tuple[float, float]:
    model.eval()

    total_loss = 0.0
    total_psnr = 0.0
    total_batches = 0

    with torch.inference_mode():
        for input_images, target_images, _ in loader:
            input_images = input_images.to(
                device,
                non_blocking=True,
            )
            target_images = target_images.to(
                device,
                non_blocking=True,
            )

            predictions = model(input_images)
            loss, _ = criterion(predictions, target_images)

            total_loss += loss.item()
            total_psnr += calculate_psnr(
                predictions,
                target_images,
            )
            total_batches += 1

    if total_batches == 0:
        raise RuntimeError(
            "De validatiedataset bevat geen batches."
        )

    return (
        total_loss / total_batches,
        total_psnr / total_batches,
    )


def save_training_preview(
    model: nn.Module,
    loader: DataLoader,
    device: torch.device,
    output_path: Path,
) -> None:
    model.eval()

    with torch.inference_mode():
        input_images, target_images, _ = next(iter(loader))

        input_images = input_images[:4].to(device)
        target_images = target_images[:4].to(device)
        predictions = model(input_images)

        rows = []

        for index in range(input_images.shape[0]):
            rows.extend(
                [
                    input_images[index].cpu(),
                    predictions[index].cpu(),
                    target_images[index].cpu(),
                ]
            )

        grid = make_grid(
            rows,
            nrow=3,
            padding=8,
            pad_value=1.0,
        )

        output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        save_image(grid, output_path)


def train(config: Config) -> None:
    set_seed(config.seed)

    device = get_device()
    output_dir = Path(config.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Apparaat: {device}")
    print("Dataset laden...")

    if getattr(config, "use_database", True):
        connection = create_connection()
        ensure_training_photo_pairs_table(connection)
        train_dataset = DatabasePairedPhotoDataset(
            connection,
            "train",
            config.image_size,
            training=True,
        )
        val_dataset = DatabasePairedPhotoDataset(
            connection,
            "val",
            config.image_size,
            training=False,
        )
    else:
        train_dataset = PairedPhotoDataset(...)
        
        val_dataset = PairedPhotoDataset(...)   

    pin_memory = device.type == "cuda"

    train_loader = DataLoader(
        train_dataset,
        batch_size=config.batch_size,
        shuffle=True,
        num_workers=config.num_workers,
        pin_memory=pin_memory,
        drop_last=False,
    )

    val_loader = DataLoader(
        val_dataset,
        batch_size=config.batch_size,
        shuffle=False,
        num_workers=config.num_workers,
        pin_memory=pin_memory,
        drop_last=False,
    )

    model = NaturalPhotoUNet(
        base_channels=config.base_channels,
        residual_strength=config.residual_strength,
    ).to(device)

    criterion = CombinedNaturalLoss(
        config,
        device,
    )

    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=config.learning_rate,
        betas=(0.9, 0.99),
        weight_decay=1e-4,
    )

    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer,
        mode="min",
        factor=0.5,
        patience=4,
        min_lr=1e-6,
    )

    best_val_loss = float("inf")
    epochs_without_improvement = 0
    history: list[dict] = []

    print(f"Trainingsparen: {len(train_dataset)}")
    print(f"Validatieparen: {len(val_dataset)}")

    for epoch in range(1, config.epochs + 1):
        model.train()

        epoch_loss = 0.0
        component_sums: dict[str, float] = {}
        batch_count = 0

        progress = tqdm(
            train_loader,
            desc=f"Epoch {epoch}/{config.epochs}",
        )

        for input_images, target_images, _ in progress:
            input_images = input_images.to(
                device,
                non_blocking=True,
            )
            target_images = target_images.to(
                device,
                non_blocking=True,
            )

            optimizer.zero_grad(set_to_none=True)

            predictions = model(input_images)

            loss, components = criterion(
                predictions,
                target_images,
            )

            loss.backward()

            torch.nn.utils.clip_grad_norm_(
                model.parameters(),
                max_norm=config.max_gradient_norm,
            )

            optimizer.step()

            epoch_loss += loss.item()
            batch_count += 1

            for key, value in components.items():
                component_sums[key] = (
                    component_sums.get(key, 0.0) + value
                )

            progress.set_postfix(
                loss=f"{loss.item():.4f}",
                exposure=f"{components['exposure']:.4f}",
                highlights=f"{components['highlights']:.4f}",
            )

        train_loss = epoch_loss / max(batch_count, 1)

        val_loss, val_psnr = run_validation(
            model,
            val_loader,
            criterion,
            device,
        )

        scheduler.step(val_loss)

        current_lr = optimizer.param_groups[0]["lr"]

        epoch_record = {
            "epoch": epoch,
            "train_loss": train_loss,
            "val_loss": val_loss,
            "val_psnr": val_psnr,
            "learning_rate": current_lr,
            "components": {
                key: value / max(batch_count, 1)
                for key, value in component_sums.items()
            },
        }

        history.append(epoch_record)

        with open(
            output_dir / "history.json",
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                history,
                file,
                indent=2,
                ensure_ascii=False,
            )

        save_training_preview(
            model,
            val_loader,
            device,
            output_dir / "previews" / f"epoch_{epoch:03d}.jpg",
        )

        print(
            f"Epoch {epoch}: "
            f"train loss={train_loss:.5f}, "
            f"val loss={val_loss:.5f}, "
            f"PSNR={val_psnr:.2f}, "
            f"lr={current_lr:.7f}"
        )

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            epochs_without_improvement = 0

            save_checkpoint(
                Path(config.checkpoint_path),
                model,
                optimizer,
                scheduler,
                epoch,
                best_val_loss,
                config,
            )

            print(
                f"Beste model opgeslagen: "
                f"{config.checkpoint_path}"
            )
        else:
            epochs_without_improvement += 1

            if (
                epochs_without_improvement
                >= config.early_stopping_patience
            ):
                print(
                    "Training gestopt door early stopping."
                )
                break


def pil_to_numpy(image: Image.Image) -> np.ndarray:
    return np.asarray(image).astype(np.float32) / 255.0


def numpy_to_pil(image: np.ndarray) -> Image.Image:
    image = np.clip(image, 0.0, 1.0)
    image_uint8 = np.round(image * 255.0).astype(np.uint8)
    return Image.fromarray(image_uint8, mode="RGB")


def soft_highlight_compression(
    image: np.ndarray,
    threshold: float = 0.82,
    compression: float = 0.45,
) -> np.ndarray:
    """
    Comprimeert alleen het lichte bereik.

    Donkere en middengrijze pixels blijven hierdoor vrijwel gelijk.
    """

    image = np.clip(image, 0.0, 1.0)

    compressed = image.copy()
    mask = image > threshold

    distance = image[mask] - threshold

    compressed[mask] = (
        threshold
        + distance / (1.0 + compression * distance * 8.0)
    )

    return np.clip(compressed, 0.0, 1.0)


def controlled_histogram_match(
    generated: np.ndarray,
    reference: np.ndarray,
    amount: float,
) -> np.ndarray:
    amount = float(np.clip(amount, 0.0, 1.0))

    if amount == 0.0:
        return generated

    matched = match_histograms(
        generated,
        reference,
        channel_axis=-1,
    )

    matched = np.clip(matched, 0.0, 1.0)

    return np.clip(
        generated * (1.0 - amount) + matched * amount,
        0.0,
        1.0,
    )


def process_full_resolution_image(
    model: nn.Module,
    input_image: Image.Image,
    device: torch.device,
    model_size: int,
    correction_strength: float,
    histogram_amount: float,
    compress_highlights: bool,
) -> tuple[Image.Image, Image.Image]:
    original_size = input_image.size
    input_array = pil_to_numpy(input_image)

    model_image = resize_and_center_crop(
        input_image,
        model_size,
    )

    model_tensor = TF.to_tensor(
        model_image
    ).unsqueeze(0).to(device)

    with torch.inference_mode():
        model_output = model(model_tensor)[0].cpu()

    raw_output_image = TF.to_pil_image(model_output)
    raw_output_image = raw_output_image.resize(
        original_size,
        Image.Resampling.LANCZOS,
    )

    raw_output_array = pil_to_numpy(raw_output_image)

    correction_strength = float(
        np.clip(correction_strength, 0.0, 1.0)
    )

    blended = (
        input_array * (1.0 - correction_strength)
        + raw_output_array * correction_strength
    )

    if compress_highlights:
        blended = soft_highlight_compression(
            blended,
            threshold=0.84,
            compression=0.35,
        )

    blended = controlled_histogram_match(
        generated=blended,
        reference=input_array,
        amount=histogram_amount,
    )

    final_image = numpy_to_pil(blended)

    return raw_output_image, final_image


def create_comparison(
    original: Image.Image,
    raw_output: Image.Image,
    final_output: Image.Image,
) -> Image.Image:
    width, height = original.size

    raw_output = raw_output.resize(
        (width, height),
        Image.Resampling.LANCZOS,
    )

    final_output = final_output.resize(
        (width, height),
        Image.Resampling.LANCZOS,
    )

    comparison = Image.new(
        "RGB",
        (width * 3, height),
        color=(255, 255, 255),
    )

    comparison.paste(original, (0, 0))
    comparison.paste(raw_output, (width, 0))
    comparison.paste(final_output, (width * 2, 0))

    return comparison


def get_reference_photos() -> list[str]:
    REFERENCE_PHOTOS_DIR.mkdir(parents=True, exist_ok=True)

    try:
        with create_connection() as connection:
            ensure_photo_references_table(connection)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT filename, image_data
                    FROM photo_references
                    ORDER BY created_at, filename
                    """
                )
                database_photos = cursor.fetchall()

        for filename, image_data in database_photos:
            (REFERENCE_PHOTOS_DIR / Path(filename).name).write_bytes(
                bytes(image_data)
            )

    except Exception as error:
        logger.warning(
            "Referentiefoto's uit de database konden niet worden geladen: %s",
            error,
        )

    return [
        str(path)
        for path in sorted(REFERENCE_PHOTOS_DIR.iterdir())
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    ]


def add_reference_photos(input_images) -> list[str]:
    if not input_images:
        return get_reference_photos()

    REFERENCE_PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
    images = input_images if isinstance(input_images, list) else [input_images]

    database_images = []

    for image in images:
        source = Path(image if isinstance(image, str) else image.name)

        if not source.is_file() or source.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue

        image_data = source.read_bytes()
        database_images.append((source.name, image_data))

    try:
        with create_connection() as connection:
            ensure_photo_references_table(connection)
            with connection.cursor() as cursor:
                for filename, image_data in database_images:
                    cursor.execute(
                        """
                        INSERT INTO photo_references (
                            id,
                            filename,
                            content_type,
                            checksum_sha256,
                            image_data
                        )
                        VALUES (
                            %s,
                            %s,
                            %s,
                            %s,
                            %s
                        )
                        ON CONFLICT (checksum_sha256) DO NOTHING
                        """,
                        (
                            uuid4(),
                            filename,
                            mimetypes.guess_type(filename)[0]
                            or "application/octet-stream",
                            hashlib.sha256(image_data).hexdigest(),
                            image_data,
                        ),
                    )

    except Exception as error:
        logger.warning(
            "Referentiefoto's konden niet in de database worden opgeslagen: %s",
            error,
        )

    for filename, image_data in database_images:
        (REFERENCE_PHOTOS_DIR / Path(filename).name).write_bytes(image_data)

    return get_reference_photos()


def edit_photo(
    input_image: str,
    prompt: str | None = None,
    logo: bool = False,
    opacity: float = 50,
    logo_position: str = "Midden",
):
    del prompt, logo, opacity, logo_position

    device = get_device()
    model, config = load_model_from_checkpoint(
        "outputs/best_model.pt",
        device,
    )
    original = open_rgb_image(Path(input_image))

    _, final_output = process_full_resolution_image(
        model=model,
        input_image=original,
        device=device,
        model_size=config.image_size,
        correction_strength=0.45,
        histogram_amount=0.20,
        compress_highlights=True,
    )

    return final_output, "Foto aangepast met het getrainde model."


def predict(
    checkpoint_path: str,
    input_path: str,
    output_path: str,
    correction_strength: float,
    histogram_amount: float,
    preview: bool,
    compress_highlights: bool,
) -> None:
    device = get_device()

    model, config = load_model_from_checkpoint(
        checkpoint_path,
        device,
    )

    input_path_object = Path(input_path)

    if not input_path_object.exists():
        raise FileNotFoundError(
            f"Inputfoto bestaat niet: {input_path_object}"
        )

    input_image = open_rgb_image(input_path_object)

    raw_output, final_output = process_full_resolution_image(
        model=model,
        input_image=input_image,
        device=device,
        model_size=config.image_size,
        correction_strength=correction_strength,
        histogram_amount=histogram_amount,
        compress_highlights=compress_highlights,
    )

    output_path_object = Path(output_path)
    output_path_object.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    final_output.save(
        output_path_object,
        quality=95,
        subsampling=0,
    )

    print(f"Eindresultaat opgeslagen: {output_path_object}")

    if preview:
        preview_path = output_path_object.with_name(
            f"{output_path_object.stem}_vergelijking.jpg"
        )

        comparison = create_comparison(
            input_image,
            raw_output,
            final_output,
        )

        comparison.save(
            preview_path,
            quality=92,
            subsampling=0,
        )

        print(
            "Vergelijking opgeslagen. Volgorde: "
            "origineel | ruwe modeloutput | veilige output"
        )
        print(f"Preview: {preview_path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Train en gebruik een natuurlijk fotomodificatiemodel "
            "met bescherming tegen overbelichting."
        )
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    train_parser = subparsers.add_parser(
        "train",
        help="Train het model.",
    )

    train_parser.add_argument(
        "--epochs",
        type=int,
        default=60,
    )

    train_parser.add_argument(
        "--batch-size",
        type=int,
        default=2,
    )

    train_parser.add_argument(
        "--image-size",
        type=int,
        default=512,
    )

    train_parser.add_argument(
        "--learning-rate",
        type=float,
        default=2e-4,
    )

    train_parser.add_argument(
        "--train-input-dir",
        default="data/train/input",
    )

    train_parser.add_argument(
        "--train-target-dir",
        default="data/train/target",
    )

    train_parser.add_argument(
        "--val-input-dir",
        default="data/val/input",
    )

    train_parser.add_argument(
        "--val-target-dir",
        default="data/val/target",
    )

    train_parser.add_argument(
        "--checkpoint",
        default="outputs/best_model.pt",
    )

    predict_parser = subparsers.add_parser(
        "predict",
        help="Bewerk één foto.",
    )

    predict_parser.add_argument(
        "--checkpoint",
        default="outputs/best_model.pt",
    )

    predict_parser.add_argument(
        "--input",
        required=True,
    )

    predict_parser.add_argument(
        "--output",
        default="resultaat.jpg",
    )

    predict_parser.add_argument(
        "--strength",
        type=float,
        default=0.45,
        help=(
            "Hoeveel van de modelcorrectie wordt toegepast. "
            "Aanbevolen: 0.30 tot 0.55."
        ),
    )

    predict_parser.add_argument(
        "--histogram-amount",
        type=float,
        default=0.20,
        help=(
            "Hoe sterk de output terug wordt gekoppeld aan het "
            "histogram van het origineel. Aanbevolen: 0.10 tot 0.30."
        ),
    )

    predict_parser.add_argument(
        "--preview",
        action="store_true",
        help=(
            "Sla een vergelijking op zonder andere bestanden "
            "te overschrijven."
        ),
    )

    predict_parser.add_argument(
        "--no-highlight-compression",
        action="store_true",
        help="Schakel highlightcompressie uit.",
    )

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "train":
        config = Config(
            train_input_dir=args.train_input_dir,
            train_target_dir=args.train_target_dir,
            val_input_dir=args.val_input_dir,
            val_target_dir=args.val_target_dir,
            checkpoint_path=args.checkpoint,
            epochs=args.epochs,
            batch_size=args.batch_size,
            image_size=args.image_size,
            learning_rate=args.learning_rate,
        )

        train(config)

    elif args.command == "predict":
        predict(
            checkpoint_path=args.checkpoint,
            input_path=args.input,
            output_path=args.output,
            correction_strength=args.strength,
            histogram_amount=args.histogram_amount,
            preview=args.preview,
            compress_highlights=(
                not args.no_highlight_compression
            ),
        )


if __name__ == "__main__":
    main()