from dataclasses import dataclass


@dataclass(frozen=True)
class TextChunk:
    chunk_number: int
    content: str
    character_start: int
    character_end: int


def split_text_into_chunks(
    text: str,
    chunk_size: int = 1200,
    overlap: int = 200,
) -> list[TextChunk]:
    if chunk_size <= 0:
        raise ValueError(
            "chunk_size moet groter zijn dan 0."
        )

    if overlap < 0:
        raise ValueError(
            "overlap mag niet negatief zijn."
        )

    if overlap >= chunk_size:
        raise ValueError(
            "overlap moet kleiner zijn dan chunk_size."
        )

    text = text.strip()

    if not text:
        return []

    chunks = []
    text_length = len(text)
    start = 0
    chunk_number = 0

    while start < text_length:
        proposed_end = min(start + chunk_size, text_length)
        end = proposed_end

        if proposed_end < text_length:
            search_start = start + max(chunk_size // 2, 1)
            search_window = text[search_start:proposed_end]
            boundaries = [
                search_window.rfind("\n\n"),
                search_window.rfind(". "),
                search_window.rfind("? "),
                search_window.rfind("! "),
                search_window.rfind("\n"),
                search_window.rfind(" "),
            ]
            best_boundary = max(boundaries)

            if best_boundary != -1:
                end = search_start + best_boundary + 1

        if end <= start:
            end = proposed_end

        raw_chunk = text[start:end]
        content = raw_chunk.strip()

        if content:
            leading_spaces = len(raw_chunk) - len(raw_chunk.lstrip())
            trailing_spaces = len(raw_chunk) - len(raw_chunk.rstrip())
            chunks.append(
                TextChunk(
                    chunk_number=chunk_number,
                    content=content,
                    character_start=start + leading_spaces,
                    character_end=end - trailing_spaces,
                )
            )
            chunk_number += 1

        if end >= text_length:
            break

        next_start = end - overlap
        if next_start <= start:
            next_start = end

        start = next_start

    return chunks