from __future__ import annotations

from pathlib import Path


class LocalPathStorage:
    def __init__(self,root:Path)->None:self.root=root.resolve()

    def safe_path(self,relative_path:str)->Path:
        if Path(relative_path).is_absolute():raise ValueError("Managed path phải là đường dẫn tương đối.")
        resolved=(self.root/relative_path).resolve()
        if self.root not in resolved.parents:raise ValueError("Managed path nằm ngoài storage root.")
        return resolved

    def resolve_existing(self,relative_path:str)->Path:
        path=self.safe_path(relative_path)
        if not path.is_file() or path.is_symlink():raise FileNotFoundError(relative_path)
        return path
