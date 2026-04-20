import hashlib
import katpoint
import pytest

import kattelmod
from kattelmod.component import TelstateUpdatingComponent
from kattelmod.session import CaptureState

ARGS = [
    '--config=mkat/fake_2ant.cfg',
    '--description=Unit test',
    '--dry-run',
    '--start-time=2023-04-17 23:24:00',
    'azel, 0, 70',
]


@pytest.fixture
def session():
    return kattelmod.session_from_commandline(targets=True, args=ARGS)


@pytest.fixture
def args(session):
    return session.argparser().parse_args(ARGS)


@pytest.fixture
def event_loop(session, args):
    loop = session.make_event_loop(args)
    yield loop
    loop.close()


async def _telstate_get(s, key):
    """Ensure that component associated with `key` has been flushed."""
    telstate = s.telstate
    component_name = key.split(telstate.SEPARATOR)[0]
    component = getattr(s, component_name, None)
    if component and isinstance(component, TelstateUpdatingComponent):
        await component._flush()
    return await telstate[key]


async def test_session(session, args):
    assert session.state == CaptureState.UNKNOWN
    async with await session.connect(args):
        assert session.state == CaptureState.STARTED
        assert session.dry_run
        telstate_obs_params = await _telstate_get(session, 'obs_params')
        assert session.obs_params == telstate_obs_params
        target = session.targets.targets[0]
        assert target == katpoint.Target('azel, 0, 70')
        session.label = 'track'
        assert await _telstate_get(session, 'obs_label') == 'track'
        await session.track(target, duration=10)
        assert await _telstate_get(session, 'obs_activity') == 'track'
    assert session.state == CaptureState.UNCONFIGURED


async def test_session_serialises_vlbi_catalogue_into_telstate(tmp_path):
    catalogue_path = tmp_path / "vlbi_cat_ep134f.csv"
    catalogue_text = "# EXPERIMENT EP134F\nJ0000-0000, radec, 00:00:00, -00:00:00, scan No0001, 2026-03-11 21:43:22.000, 10\n"
    catalogue_path.write_text(catalogue_text, encoding="utf-8")
    args_list = [
        '--config=mkat/fake_2ant.cfg',
        '--description=Unit test',
        '--dry-run',
        f'--vlbi-catalogue={catalogue_path}',
        '--start-time=2023-04-17 23:24:00',
        'azel, 0, 70',
    ]
    session = kattelmod.session_from_commandline(targets=True, args=args_list)
    args = session.argparser().parse_args(args_list)

    async with await session.connect(args):
        telstate_obs_params = await _telstate_get(session, 'obs_params')
        assert telstate_obs_params["vlbi"] == {
            "catalogue_format": "csv",
            "catalogue_name": "vlbi_cat_ep134f.csv",
            "catalogue_sha256": hashlib.sha256(catalogue_text.encode("utf-8")).hexdigest(),
            "experiment": "ep134f",
        }
        assert "vlbi_catalogue" not in telstate_obs_params
        assert await session.telstate["vlbi_experiment"] == "ep134f"
        assert await session.telstate["vlbi_catalogue_name"] == "vlbi_cat_ep134f.csv"
        assert await session.telstate["vlbi_catalogue_format"] == "csv"
        assert await session.telstate["vlbi_catalogue_sha256"] == hashlib.sha256(
            catalogue_text.encode("utf-8")
        ).hexdigest()
        assert await session.telstate["vlbi_catalogue_content"] == catalogue_text
