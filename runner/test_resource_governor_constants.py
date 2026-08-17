#!/usr/bin/env python3
"""Test resource_governor named constants for magic number elimination."""

import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import runner.resource_governor as rg


def test_disk_soft_constant_exists():
    """Verify DEFAULT_DISK_SOFT_PCT named constant is defined."""
    assert hasattr(rg, 'DEFAULT_DISK_SOFT_PCT')
    assert rg.DEFAULT_DISK_SOFT_PCT == 80.0


def test_disk_hard_constant_exists():
    """Verify DEFAULT_DISK_HARD_PCT named constant is defined."""
    assert hasattr(rg, 'DEFAULT_DISK_HARD_PCT')
    assert rg.DEFAULT_DISK_HARD_PCT == 90.0


def test_ram_hard_constant_exists():
    """Verify DEFAULT_RAM_HARD_PCT named constant is defined."""
    assert hasattr(rg, 'DEFAULT_RAM_HARD_PCT')
    assert rg.DEFAULT_RAM_HARD_PCT == 82.0


def test_disk_soft_reads_from_env():
    """_disk_soft() uses constant as default; env var overrides it."""
    os.environ.pop('DISK_SOFT_PCT', None)
    assert rg._disk_soft() == rg.DEFAULT_DISK_SOFT_PCT

    os.environ['DISK_SOFT_PCT'] = '75'
    assert rg._disk_soft() == 75.0

    os.environ.pop('DISK_SOFT_PCT')


def test_disk_hard_reads_from_env():
    """_disk_hard() uses constant as default; env var overrides it."""
    os.environ.pop('DISK_HARD_PCT', None)
    assert rg._disk_hard() == rg.DEFAULT_DISK_HARD_PCT

    os.environ['DISK_HARD_PCT'] = '88'
    assert rg._disk_hard() == 88.0

    os.environ.pop('DISK_HARD_PCT')


def test_ram_hard_reads_from_env():
    """_ram_hard() uses constant as default; env var overrides it."""
    os.environ.pop('RAM_HARD_PCT', None)
    assert rg._ram_hard() == rg.DEFAULT_RAM_HARD_PCT

    os.environ['RAM_HARD_PCT'] = '79'
    assert rg._ram_hard() == 79.0

    os.environ.pop('RAM_HARD_PCT')


def test_fleet_tunable_via_env():
    """Thresholds are fleet-tunable via env-vars for fleet_control."""
    # All three can be overridden independently via env-vars
    os.environ['DISK_SOFT_PCT'] = '70'
    os.environ['DISK_HARD_PCT'] = '85'
    os.environ['RAM_HARD_PCT'] = '78'

    assert rg._disk_soft() == 70.0
    assert rg._disk_hard() == 85.0
    assert rg._ram_hard() == 78.0

    os.environ.pop('DISK_SOFT_PCT')
    os.environ.pop('DISK_HARD_PCT')
    os.environ.pop('RAM_HARD_PCT')


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
