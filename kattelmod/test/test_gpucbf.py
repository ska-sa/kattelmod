from types import SimpleNamespace
from unittest import mock

from kattelmod.systems.mkat.gpucbf import CorrelatorBeamformer


def _inform(stream: str, state: str) -> SimpleNamespace:
    return SimpleNamespace(arguments=[stream.encode("utf-8"), b"239.0.0.1:7148", state.encode("utf-8")])


class TestCorrelatorBeamformer:
    async def test_capture_start_without_vlbi_stream(self) -> None:
        cbf = CorrelatorBeamformer()
        cbf._client = mock.Mock()
        cbf._client._client = mock.Mock()
        cbf._client._client.request = mock.AsyncMock(
            side_effect=[
                (
                    [b"ok"],
                    [
                        _inform("antenna_channelised_voltage", "up"),
                        _inform("baseline_correlation_products", "down"),
                    ],
                ),
                ([b"ok"], []),
            ]
        )

        await cbf.capture_start()

        assert cbf._client._client.request.await_args_list == [
            mock.call("capture-list"),
            mock.call("capture-start", "baseline_correlation_products"),
        ]

    async def test_capture_start_with_vlbi_streams(self) -> None:
        cbf = CorrelatorBeamformer()
        cbf._client = mock.Mock()
        cbf._client._client = mock.Mock()
        cbf._client._client.request = mock.AsyncMock(
            side_effect=[
                (
                    [b"ok"],
                    [
                        _inform("antenna_channelised_voltage", "up"),
                        _inform("baseline_correlation_products", "down"),
                        _inform("tied_array_channelised_voltage_0x", "down"),
                        _inform("tied_array_channelised_voltage_0y", "down"),
                        _inform("tied_array_resampled_voltage", "down"),
                    ],
                ),
                ([b"ok"], []),
                ([b"ok"], []),
                ([b"ok"], []),
                ([b"ok"], []),
                ([b"ok"], []),
                ([b"ok"], []),
            ]
        )

        await cbf.capture_start()

        assert cbf._client._client.request.await_args_list == [
            mock.call("capture-list"),
            mock.call("capture-start", "baseline_correlation_products"),
            mock.call("capture-start", "tied_array_channelised_voltage_0x"),
            mock.call("capture-start", "tied_array_channelised_voltage_0y"),
            mock.call("capture-start", "tied_array_resampled_voltage"),
        ]

    async def test_capture_stop_with_vlbi_streams(self) -> None:
        cbf = CorrelatorBeamformer()
        cbf._client = mock.Mock()
        cbf._client._client = mock.Mock()
        cbf._active_capture_streams = [
            "baseline_correlation_products",
            "tied_array_channelised_voltage_0x",
            "tied_array_channelised_voltage_0y",
            "tied_array_resampled_voltage",
        ]
        cbf._client._client.request = mock.AsyncMock(
            side_effect=[
                ([b"ok"], []),
                ([b"ok"], []),
                ([b"ok"], []),
                ([b"ok"], []),
            ]
        )

        await cbf.capture_stop()

        assert cbf._client._client.request.await_args_list == [
            mock.call("capture-stop", "baseline_correlation_products"),
            mock.call("capture-stop", "tied_array_channelised_voltage_0x"),
            mock.call("capture-stop", "tied_array_channelised_voltage_0y"),
            mock.call("capture-stop", "tied_array_resampled_voltage"),
        ]
        assert cbf._active_capture_streams == []

    async def test_capture_stop_falls_back_to_up_streams(self) -> None:
        cbf = CorrelatorBeamformer()
        cbf._client = mock.Mock()
        cbf._client._client = mock.Mock()
        cbf._client._client.request = mock.AsyncMock(
            side_effect=[
                (
                    [b"ok"],
                    [
                        _inform("antenna_channelised_voltage", "up"),
                        _inform("baseline_correlation_products", "up"),
                        _inform("tied_array_channelised_voltage_0x", "up"),
                        _inform("tied_array_channelised_voltage_0y", "up"),
                        _inform("tied_array_resampled_voltage", "up"),
                    ],
                ),
                ([b"ok"], []),
                ([b"ok"], []),
                ([b"ok"], []),
                ([b"ok"], []),
                ([b"ok"], []),
            ]
        )

        await cbf.capture_stop()

        assert cbf._client._client.request.await_args_list == [
            mock.call("capture-list"),
            mock.call("capture-stop", "baseline_correlation_products"),
            mock.call("capture-stop", "tied_array_channelised_voltage_0x"),
            mock.call("capture-stop", "tied_array_channelised_voltage_0y"),
            mock.call("capture-stop", "tied_array_resampled_voltage"),
        ]
