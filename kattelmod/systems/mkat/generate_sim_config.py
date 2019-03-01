#!/usr/bin/env python


import argparse
import string
import json
import sys


TEMPLATE = string.Template("""\
[Telescope mkat]
ants* = fake.AntennaPositioner
sub = fake.Subarray
env = fake.Environment
cbf = sdp.CorrelatorBeamformer
sdp = sdp.ScienceDataProcessor
obs = fake.Observation

[ants]
names = ${ants}

[sub]
product = "kattelmod"
dump_rate = ${dump_rate}
pool_resources = "${ants},cbf_1,sdp_1"

[sdp]
master_controller = "${mc}:5001"
config = ${config}
""")

# Roughly based on the hand-coded files with various numbers of antennas, but
# fairly arbitrary.
ANTENNA_ORDER = [62, 63, 0, 2, 4, 6, 8, 11, 13, 15, 17, 19, 22, 30, 39, 56,
                 1, 3, 5, 7, 10, 12, 14, 18, 20, 21, 24, 25, 31, 34, 36, 42,
                 49, 57, 58, 59, 60, 61, 9, 16, 23, 26, 27, 28, 29, 32, 33, 35,
                 37, 38, 40, 41, 43, 44, 45, 46, 47, 48, 50, 51, 52, 53, 54, 55]
assert sorted(ANTENNA_ORDER) == list(range(64))
MASTER_MAP = {
    'site': 'mc1.sdp.mkat.karoo.kat.ac.za',
    'rts': 'sdprts.sdp.mkat-rts.karoo.kat.ac.za',
    'lab': 'lab1.sdp.kat.ac.za',
    'localhost': 'localhost'
}


def generate(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument('-a', '--antennas', type=int, required=True)
    parser.add_argument('-r', '--dump-rate', type=float, default=0.25)
    parser.add_argument('-c', '--channels', type=int, choices=[1024, 4096, 32768], default=4096)
    parser.add_argument('-m', '--master', choices=list(MASTER_MAP.keys()), default='lab')
    parser.add_argument('--develop', action='store_true')
    parser.add_argument('--band', choices=['l'], default='l')
    parser.add_argument('--beamformer', choices=['none', 'engineering', 'ptuse'],
                        default='none')
    args = parser.parse_args(argv)

    cbf_ants = 4
    while cbf_ants < args.antennas:
        cbf_ants *= 2
    groups = 4 * cbf_ants
    bandwidth = 856000000.0
    # Round CBF integration time of 0.5s to nearest integer multiple
    n_accs = int(round(0.5 * bandwidth / args.channels / 256)) * 256
    cbf_int_time = n_accs * args.channels / bandwidth
    # Continuum factor for a 1K continuum stream. When input is 1K, just make it
    # a 512 channel stream (less effort than trying to turn off continuum output
    # completely).
    continuum_factor = max(2, args.channels // 1024)
    config = {
        "version": "2.2",
        "inputs": {
            "i0_antenna_channelised_voltage": {
                "type": "cbf.antenna_channelised_voltage",
                "url": "spead://239.102.1.0+{}:7148".format(groups - 1),
                "n_chans": args.channels,
                "n_pols": 2,
                "adc_sample_rate": bandwidth * 2,
                "bandwidth": bandwidth,
                "n_samples_between_spectra": 2 * args.channels,
                "instrument_dev_name": "i0"
            },
            "i0_baseline_correlation_products": {
                "type": "cbf.baseline_correlation_products",
                "url": "spead://239.102.2.0+{}:7148".format(groups - 1),
                "src_streams": ["i0_antenna_channelised_voltage"],
                "int_time": cbf_int_time,
                "n_bls": cbf_ants * (cbf_ants + 1) * 2,
                "xeng_out_bits_per_sample": 32,
                "n_chans_per_substream": args.channels // groups,
                "instrument_dev_name": "i0",
                "simulate": {
                    "center_freq": 1284000000.0,
                    "sources": [
                        "PKS 1934-63, radec, 19:39:25.03, -63:42:45.7, (200.0 12000.0 -11.11 7.777 -1.231)",
                        "PKS 0408-65, radec, 4:08:20.38, -65:45:09.1, (800.0 8400.0 -3.708 3.807 -0.7202)",
                        "3C286, radec, 13:31:08.29, +30:30:33.0,(800.0 43200.0 0.956 0.584 -0.1644)"
                    ]
                }
            }
        },
        "outputs": {
            "sdp_l0": {
                "type": "sdp.vis",
                "src_streams": ["i0_baseline_correlation_products"],
                "continuum_factor": 1,
                "archive": True
            },
            "sdp_l0_continuum": {
                "type": "sdp.vis",
                "src_streams": ["i0_baseline_correlation_products"],
                "continuum_factor": continuum_factor,
                "archive": True
            },
            "cal": {
                "type": "sdp.cal",
                "src_streams": ["sdp_l0"]
            },
            "sdp_l1_flags": {
                "type": "sdp.flags",
                "src_streams": ["sdp_l0"],
                "calibration": ["cal"],
                "archive": True
            },
            "sdp_l1_flags_continuum": {
                "type": "sdp.flags",
                "src_streams": ["sdp_l0_continuum"],
                "calibration": ["cal"],
                "archive": True
            }
        },
        "config": {}
    }
    if args.beamformer != 'none':
        for (pol, addr) in [('x', '239.102.3.0'), ('y', '239.102.4.0')]:
            config["inputs"]["i0_tied_array_channelised_voltage_0" + pol] = {
                "type": "cbf.tied_array_channelised_voltage",
                "url": "spead://{}+{}:7148".format(addr, groups - 1),
                "src_streams": ["i0_antenna_channelised_voltage"],
                "spectra_per_heap": 256,
                "n_chans_per_substream": args.channels // groups,
                "beng_out_bits_per_sample": 8,
                "instrument_dev_name": "i0",
                "simulate": {
                    "center_freq": 1284000000.0,
                    "sources": [
                        "PKS 1934-63, radec, 19:39:25.03, -63:42:45.7, (200.0 12000.0 -11.11 7.777 -1.231)",
                        "PKS 0408-65, radec, 4:08:20.38, -65:45:09.1, (800.0 8400.0 -3.708 3.807 -0.7202)",
                        "3C286, radec, 13:31:08.29, +30:30:33.0,(800.0 43200.0 0.956 0.584 -0.1644)"
                    ]
                }
            }
    if args.beamformer == 'ptuse':
        config["outputs"]["sdp_beamformer"] = {
            "type": "sdp.beamformer",
            "src_streams": [
                "i0_tied_array_channelised_voltage_0x",
                "i0_tied_array_channelised_voltage_0y"
            ]
        }
    elif args.beamformer == 'engineering':
        config["outputs"]["sdp_beamformer"] = {
            "type": "sdp.beamformer_engineering",
            "src_streams": [
                "i0_tied_array_channelised_voltage_0x",
                "i0_tied_array_channelised_voltage_0y"
            ],
            "output_channels": [0, args.channels],
            "store": "ram"
        }
    if args.develop:
        config["config"]["develop"] = True

    config_str = json.dumps(config, indent=4, sort_keys=True)
    # Also need to indent the whole thing, to stop the final } from
    # being in the left-most column.
    config_str = config_str.replace('\n', '\n    ')
    content = TEMPLATE.substitute(
        ants=','.join('m{:03}'.format(ant) for ant in sorted(ANTENNA_ORDER[:args.antennas])),
        mc=MASTER_MAP[args.master],
        dump_rate=args.dump_rate,
        channels=args.channels,
        config=config_str)
    return content


if __name__ == '__main__':
    argv = sys.argv[1:]
    if argv == ['update']:
        with open('sim_64ant_32k.cfg', 'w') as f:
            f.write(generate(['--antennas', '64', '--channels', '32768']))
    else:
        print(generate(argv))
