"""Tadash registry for the pinned upstream GMR motion_retarget.py module."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ROBOT_XML_DICT = {"nasuraya_v03": ROOT / "assets/nasuraya_articulated_v03/nasuraya.xml"}
IK_CONFIG_DICT = {"calibration": {"nasuraya_v03": Path(__file__).with_name("v03.json")}}
