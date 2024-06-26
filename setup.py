#!/usr/bin/env python
from setuptools import setup, find_packages

setup(name="kattelmod",
      description="Karoo Array Telescope telescope model library'",
      author="Ludwig Schwardt",
      author_email="ludwig@ska.ac.za",
      packages=find_packages(),
      url='https://github.com/ska-sa/kattelmod',
      classifiers=[
          "Development Status :: 3 - Alpha",
          "Intended Audience :: Developers",
          "License :: Other/Proprietary License",
          "Operating System :: OS Independent",
          "Programming Language :: Python",
          "Topic :: Software Development :: Libraries :: Python Modules",
          "Topic :: Scientific/Engineering :: Astronomy"],
      platforms=["OS Independent"],
      keywords="meerkat ska",
      # Include the contents of MANIFEST.in (the system config files)
      include_package_data=True,
      package_data={'': ['systems/*/*.cfg', 'systems/*/*.txt']},
      zip_safe=False,
      setup_requires=['katversion'],
      use_katversion=True,
      python_requires='>=3.7',     # Required by katsdptelstate[aio]
      tests_require=["async-solipsism", "pytest", "pytest-asyncio"],
      install_requires=["numpy", "aiokatcp", "async-timeout", "katpoint", "katsdptelstate[aio]"])
