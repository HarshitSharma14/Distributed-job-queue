"""Local verification and installation of explicitly trusted handler bundles."""

from __future__ import annotations

import importlib.util
import json
import re
import stat
import sys
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from types import ModuleType
from zipfile import BadZipFile, ZipFile, is_zipfile

from distributed_job_queue.workers.gateway_client import DownloadedHandlerBundle
from distributed_job_queue.workers.handlers import HandlerRegistry


class InvalidDownloadedHandler(ValueError):
    """Raised when downloaded handler bytes cannot be safely installed."""


@dataclass(slots=True)
class InstalledHandlerBundle:
    """Own the temporary files for one loaded handler until worker shutdown."""

    _directory: TemporaryDirectory[str]
    _module_name: str
    _module: ModuleType

    def close(self) -> None:
        sys.modules.pop(self._module_name, None)
        self._directory.cleanup()


def install_downloaded_handler(
    registry: HandlerRegistry,
    bundle: DownloadedHandlerBundle,
    *,
    max_uncompressed_bytes: int,
) -> InstalledHandlerBundle:
    """Validate, extract, import, and register one opted-in remote handler."""

    manifest, archive = _inspect_archive(
        bundle.content,
        expected_job_type=bundle.job_type,
        max_uncompressed_bytes=max_uncompressed_bytes,
    )
    directory = TemporaryDirectory(prefix="djq-handler-")
    root = Path(directory.name)
    try:
        with archive:
            for entry in archive.infolist():
                if entry.is_dir():
                    continue
                destination = root.joinpath(*PurePosixPath(entry.filename).parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(archive.read(entry))

        module_name, callable_name = manifest["entrypoint"].split(":", 1)
        module_path = root / (module_name.replace(".", "/") + ".py")
        synthetic_name = f"_djq_handler_{bundle.digest}"
        specification = importlib.util.spec_from_file_location(
            synthetic_name, module_path
        )
        if specification is None or specification.loader is None:
            raise InvalidDownloadedHandler("Handler entrypoint cannot be loaded")
        module = importlib.util.module_from_spec(specification)
        sys.modules[synthetic_name] = module
        specification.loader.exec_module(module)
        handler = getattr(module, callable_name, None)
        if not callable(handler):
            raise InvalidDownloadedHandler("Handler entrypoint is not callable")
        registry.register(bundle.job_type, handler)
        return InstalledHandlerBundle(directory, synthetic_name, module)
    except Exception:
        sys.modules.pop(f"_djq_handler_{bundle.digest}", None)
        directory.cleanup()
        raise


def _inspect_archive(
    content: bytes,
    *,
    expected_job_type: str,
    max_uncompressed_bytes: int,
) -> tuple[dict[str, str], ZipFile]:
    source = BytesIO(content)
    if not is_zipfile(source):
        raise InvalidDownloadedHandler("Handler artifact is not a valid ZIP archive")
    source.seek(0)
    try:
        archive = ZipFile(source)
        entries = archive.infolist()
        names: set[str] = set()
        total_size = 0
        for entry in entries:
            path = PurePosixPath(entry.filename)
            if (
                "\\" in entry.filename
                or path.is_absolute()
                or ".." in path.parts
                or (path.parts and ":" in path.parts[0])
                or entry.filename in names
                or stat.S_IFMT(entry.external_attr >> 16) == stat.S_IFLNK
            ):
                raise InvalidDownloadedHandler("Handler archive contains an unsafe path")
            names.add(entry.filename)
            total_size += entry.file_size
            if total_size > max_uncompressed_bytes:
                raise InvalidDownloadedHandler(
                    "Handler archive exceeds the uncompressed size limit"
                )
        if archive.testzip() is not None or "manifest.json" not in names:
            raise InvalidDownloadedHandler("Handler archive is incomplete or corrupt")
        manifest = json.loads(archive.read("manifest.json"))
    except (BadZipFile, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidDownloadedHandler("Handler archive or manifest is invalid") from exc
    except Exception:
        archive.close()
        raise

    entrypoint = manifest.get("entrypoint") if isinstance(manifest, dict) else None
    if not isinstance(manifest, dict) or manifest.get("job_type") != expected_job_type:
        archive.close()
        raise InvalidDownloadedHandler("Handler manifest Job Type does not match")
    if not isinstance(entrypoint, str) or not re.fullmatch(
        r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*", entrypoint
    ):
        archive.close()
        raise InvalidDownloadedHandler("Handler manifest entrypoint is invalid")
    module_name, _ = entrypoint.split(":", 1)
    if module_name.replace(".", "/") + ".py" not in names:
        archive.close()
        raise InvalidDownloadedHandler("Handler entrypoint module is missing")
    return manifest, archive
