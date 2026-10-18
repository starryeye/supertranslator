"""Real filesystem regressions for invocation-local anchored creator cleanup."""

from contextlib import contextmanager
import os

import pytest

from web_translator import pdf_assemble as storage


@pytest.fixture
def root(tmp_path):
    anchor = storage._open_directory_anchor(tmp_path.resolve(), "test root")
    try:
        yield anchor
    finally:
        anchor.close()


def _create(root, kind):
    if kind == "directory":
        return storage._create_child_directory(root, "created", "test child")
    return storage._create_anchored_binary_file(root, "created")


@contextmanager
def _caller_exception(inherited):
    if inherited:
        try:
            raise KeyboardInterrupt("caller interruption remains active")
        except KeyboardInterrupt:
            yield
    else:
        yield


def _assert_usable(root, kind, created):
    visible = (root.path / "created").stat()
    assert (visible.st_dev, visible.st_ino) == created.identity
    if kind == "directory":
        created.verify_visible()
        assert created.current_path() == root.path / "created"
        opened = storage._create_anchored_binary_file(created, "inside")
    else:
        opened = created
        assert root.owned_files["created"] == created.identity
    try:
        opened.stream.write(b"exact recovery\r\n")
        opened.stream.flush()
        os.fsync(opened.stream.fileno())
        opened.stream.seek(0)
        assert opened.stream.read() == b"exact recovery\r\n"
    finally:
        opened.stream.close()
    if kind == "directory":
        created.close()
    path = root.path / "created"
    assert (path / "inside" if kind == "directory" else path).read_bytes() == b"exact recovery\r\n"


@pytest.mark.parametrize("kind", ["directory", "file"])
def test_normal_creation_returns_usable_persistent_owned_entry(root, kind):
    # Catches premature close/removal on the ordinary successful path.
    _assert_usable(root, kind, _create(root, kind))


@pytest.mark.parametrize("kind", ["directory", "file"])
@pytest.mark.parametrize("error_type", [ValueError, KeyboardInterrupt])
@pytest.mark.parametrize("context", ["handler", "context-exit"])
def test_success_during_caller_exception_preserves_entry_and_original_error(
    root, kind, error_type, context
):
    # Catches cleanup confusing an inherited exception with local failure.
    original = error_type("caller failed before recovery")

    @contextmanager
    def recover_on_exit():
        try:
            yield
        finally:
            _assert_usable(root, kind, _create(root, kind))

    with pytest.raises(error_type) as raised:
        if context == "handler":
            try:
                raise original
            except BaseException:
                _assert_usable(root, kind, _create(root, kind))
                raise
        else:
            with recover_on_exit():
                raise original
    assert raised.value is original
    assert (root.path / "created").exists()


@pytest.mark.parametrize("kind", ["directory", "file"])
@pytest.mark.parametrize("inherited", [False, True])
@pytest.mark.parametrize("error_type", [storage.PdfAssemblyError, KeyboardInterrupt])
def test_local_post_creation_failure_cleans_owned_entry_and_preserves_error(
    root, monkeypatch, kind, error_type, inherited
):
    # Catches a success flag set before the final visibility validation.
    original = error_type("local final validation failed")
    real_verify = storage._DirectoryAnchor.verify_visible
    root_checks = 0

    def fail_after_creation(anchor):
        nonlocal root_checks
        real_verify(anchor)
        if anchor is root:
            root_checks += 1
            if root_checks == 2:
                assert (root.path / "created").exists()
                raise original

    monkeypatch.setattr(storage._DirectoryAnchor, "verify_visible", fail_after_creation)
    with _caller_exception(inherited):
        with pytest.raises(error_type) as raised:
            _create(root, kind)
    assert raised.value is original
    assert not (root.path / "created").exists()
    root.verify_visible()


@pytest.mark.parametrize("kind", ["directory", "file"])
@pytest.mark.parametrize("inherited", [False, True])
def test_exclusive_collision_preserves_existing_entry(root, kind, inherited):
    # Catches cleanup adopting and deleting an entry this call did not create.
    target = root.path / "created"
    if kind == "directory":
        target.mkdir()
        payload = target / "foreign"
    else:
        payload = target
    payload.write_bytes(b"preexisting foreign bytes")
    before = target.stat()
    expected_error = FileExistsError if kind == "directory" else storage.PdfAssemblyError
    with _caller_exception(inherited):
        with pytest.raises(expected_error):
            _create(root, kind)
    after = target.stat()
    assert (after.st_dev, after.st_ino) == (before.st_dev, before.st_ino)
    assert payload.read_bytes() == b"preexisting foreign bytes"


@pytest.mark.skipif(os.name == "nt", reason="POSIX post-syscall identity boundary; native Windows handles require native CI")
@pytest.mark.parametrize("kind", ["directory", "file"])
@pytest.mark.parametrize("inherited", [False, True])
def test_post_creation_identity_read_oserror_cleans_owned_entry(
    root, monkeypatch, kind, inherited
):
    # Catches clearing creation ownership for a later OSError after create succeeds.
    original = OSError("identity read failed after actual creation")
    real_stat, real_fstat = os.stat, os.fstat
    failed = False
    opened_descriptors = []

    def stat_then_fail(path, *args, **kwargs):
        nonlocal failed
        result = real_stat(path, *args, **kwargs)
        if not failed and path == "created" and kwargs.get("dir_fd") == root.descriptor:
            failed = True
            raise original
        return result

    def fstat_then_fail(descriptor):
        nonlocal failed
        result = real_fstat(descriptor)
        if not failed and descriptor != root.descriptor:
            failed = True
            opened_descriptors.append(descriptor)
            raise original
        return result

    monkeypatch.setattr(os, "stat" if kind == "directory" else "fstat",
                        stat_then_fail if kind == "directory" else fstat_then_fail)
    with _caller_exception(inherited):
        with pytest.raises(storage.PdfAssemblyError) as raised:
            _create(root, kind)
    assert raised.value.__cause__ is original
    assert not (root.path / "created").exists()
    for descriptor in opened_descriptors:
        with pytest.raises(OSError):
            real_fstat(descriptor)


@pytest.mark.skipif(os.name == "nt", reason="POSIX syscall interruption boundary; native Windows handles require native CI")
@pytest.mark.parametrize("kind", ["directory", "file"])
def test_interruption_immediately_after_exclusive_syscall_removes_owned_entry(
    root, monkeypatch, kind
):
    # Catches losing cleanup before the creator receives its new identity.
    original = KeyboardInterrupt("interrupted after actual creation")
    real_mkdir, real_open = os.mkdir, os.open

    def mkdir_then_interrupt(path, mode=0o777, *, dir_fd=None):
        real_mkdir(path, mode, dir_fd=dir_fd)
        if dir_fd == root.descriptor and path == "created":
            raise original

    def open_then_interrupt(path, flags, mode=0o777, *, dir_fd=None):
        descriptor = real_open(path, flags, mode, dir_fd=dir_fd)
        if dir_fd == root.descriptor and path == "created" and flags & os.O_EXCL:
            os.close(descriptor)
            raise original
        return descriptor

    monkeypatch.setattr(os, "mkdir" if kind == "directory" else "open",
                        mkdir_then_interrupt if kind == "directory" else open_then_interrupt)
    with pytest.raises(KeyboardInterrupt) as raised:
        _create(root, kind)
    assert raised.value is original
    assert not (root.path / "created").exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX held-entry replacement; Windows denies replacement via native sharing")
@pytest.mark.parametrize("kind", ["directory", "file"])
def test_local_failure_never_deletes_foreign_replacement(root, monkeypatch, kind):
    # Catches cleanup by name instead of the exact created identity.
    original = KeyboardInterrupt("interrupted after foreign replacement")
    real_verify = storage._DirectoryAnchor.verify_visible
    root_checks = 0
    foreign_identity = None

    def replace_after_creation(anchor):
        nonlocal root_checks, foreign_identity
        real_verify(anchor)
        if anchor is root:
            root_checks += 1
            if root_checks == 2:
                target = root.path / "created"
                target.rename(root.path / "detached-owned")
                if kind == "directory":
                    target.mkdir()
                    (target / "foreign").write_bytes(b"foreign recovery")
                else:
                    target.write_bytes(b"foreign recovery")
                result = target.stat()
                foreign_identity = (result.st_dev, result.st_ino)
                raise original

    monkeypatch.setattr(storage._DirectoryAnchor, "verify_visible", replace_after_creation)
    with pytest.raises(KeyboardInterrupt) as raised:
        _create(root, kind)
    assert raised.value is original
    target = root.path / "created"
    after = target.stat()
    assert (after.st_dev, after.st_ino) == foreign_identity
    assert (target / "foreign" if kind == "directory" else target).read_bytes() == b"foreign recovery"
