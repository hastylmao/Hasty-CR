import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest

spec = importlib.util.spec_from_file_location('emulator_reconnect',
    Path(__file__).resolve().parents[1]/'scripts/emulator.py')
emulator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(emulator)


def test_reconnect_requested_endpoint_then_verify():
    with patch.object(emulator,'packages',side_effect=[set(),{emulator.REQUIRED_PACKAGE}]), \
         patch.object(emulator.subprocess,'run') as run:
        emulator.verify()
        assert run.call_args.args[0] == [str(emulator.DEFAULT_ADB),'connect',emulator.DEFAULT_SERIAL]


def test_connected_device_does_not_reconnect():
    with patch.object(emulator,'packages',return_value={emulator.REQUIRED_PACKAGE}), \
         patch.object(emulator.subprocess,'run') as run:
        emulator.verify()
        run.assert_not_called()


def test_reconnected_coc_still_refused():
    with patch.object(emulator,'packages',side_effect=[set(),{emulator.FORBIDDEN_PACKAGE}]), \
         patch.object(emulator.subprocess,'run'):
        with pytest.raises(SystemExit,match='CLASH OF CLANS'):
            emulator.verify()


def test_failed_connection_still_refused():
    with patch.object(emulator,'packages',return_value=set()), \
         patch.object(emulator.subprocess,'run'):
        with pytest.raises(SystemExit,match='cannot reach'):
            emulator.verify()
