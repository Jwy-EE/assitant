from assistant_app.tools.permissions import PermissionBroker


def test_blocks_recursive_delete_patterns() -> None:
    broker = PermissionBroker()
    for command in [
        "Remove-Item -Recurse C:\\tmp\\x",
        "rm -rf ./data",
        "rmdir /s C:\\tmp\\x",
        "del /s *.log",
    ]:
        decision = broker.inspect_command(command)
        assert not decision.allowed
        assert decision.requires_confirmation


def test_single_file_delete_requires_confirmation() -> None:
    broker = PermissionBroker()
    decision = broker.inspect_command('Remove-Item "C:\\tmp\\file.txt"')
    assert decision.allowed
    assert decision.risk == "L4"
    assert decision.requires_confirmation

