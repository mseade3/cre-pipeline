from __future__ import annotations

import csv
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from cre_pipeline.schemas import EntityReviewImport, ParcelImport

T_co = TypeVar("T_co", bound=BaseModel, covariant=True)


class SourceAdapter(Protocol[T_co]):
    def records(self) -> Iterator[T_co]: ...


class CsvValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("\n".join(errors))
        self.errors = errors


def validated_csv[T: BaseModel](path: Path, model: type[T]) -> Iterable[T]:
    errors: list[str] = []
    records: list[T] = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise CsvValidationError(["CSV is missing a header row"])
        for row_number, row in enumerate(reader, start=2):
            try:
                records.append(model.model_validate(row))
            except ValidationError as exc:
                errors.append(f"row {row_number}: {exc}")
    if errors:
        raise CsvValidationError(errors)
    return records


class ParcelCsvAdapter:
    def __init__(self, path: Path) -> None:
        self.path = path

    def records(self) -> Iterator[ParcelImport]:
        yield from validated_csv(self.path, ParcelImport)


class EntityReviewCsvAdapter:
    def __init__(self, path: Path) -> None:
        self.path = path

    def records(self) -> Iterator[EntityReviewImport]:
        yield from validated_csv(self.path, EntityReviewImport)
