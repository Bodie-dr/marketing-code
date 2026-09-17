from __future__ import annotations

import argparse
from pathlib import Path

from database import create_connection, create_schema
from foto_model import (
    ensure_training_photo_pairs_table,
    import_local_training_pairs,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Importeer trainingsfoto-paren vanuit lokale folders "
            "naar SQLite."
        )
    )

    parser.add_argument(
        "--train-input-dir",
        type=str,
        default="data/train/input",
        help="Map met inputfoto's voor training.",
    )
    parser.add_argument(
        "--train-target-dir",
        type=str,
        default="data/train/target",
        help="Map met targetfoto's voor training.",
    )
    parser.add_argument(
        "--val-input-dir",
        type=str,
        default="data/val/input",
        help="Map met inputfoto's voor validatie.",
    )
    parser.add_argument(
        "--val-target-dir",
        type=str,
        default="data/val/target",
        help="Map met targetfoto's voor validatie.",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    connection = create_connection()
    try:
        create_schema(connection)
        ensure_training_photo_pairs_table(connection)

        train_count = import_local_training_pairs(
            connection=connection,
            split="train",
            input_dir=Path(args.train_input_dir),
            target_dir=Path(args.train_target_dir),
        )

        val_count = import_local_training_pairs(
            connection=connection,
            split="val",
            input_dir=Path(args.val_input_dir),
            target_dir=Path(args.val_target_dir),
        )

        connection.commit()
        print(
            f"Import voltooid: train={train_count}, val={val_count}"
        )
        return 0

    except Exception as error:
        connection.rollback()
        print(f"Fout bij importeren trainingsfoto's: {error}")
        return 1

    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
