#!/usr/bin/env python
from setuptools import setup, find_packages

setup (
    name="kattelmod",
    version="trunk",
    description="Karoo Array Telescope telescope model library'",
    author="Ludwig Schwardt",
    author_email="ludwig@ska.ac.za",
    packages=find_packages(),
    url='http://ska.ac.za/',
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: Other/Proprietary License",
        "Operating System :: OS Independent",
        "Programming Language :: Python",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Topic :: Scientific/Engineering :: Astronomy",
    ],
    platforms=[ "OS Independent" ],
    keywords="kat meerkat ska",
    # Include the contents of MANIFEST.in (the system config files)
    include_package_data=True,
    zip_safe=False,
    # Bitten Test Suite
    test_suite="nose.collector",
    install_requires=[
        "numpy",
        "h5py",
        "spead",
        "katcp",
        "katpoint",
        ]
)
