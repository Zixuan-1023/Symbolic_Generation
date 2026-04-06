from __future__ import annotations

from dataclasses import dataclass
from typing import Set


@dataclass
class GeneratorConfig:
    steps_per_bar: int = 16
    min_pitch: int = 48
    max_pitch: int = 84
    seed: int = 42


@dataclass
class ExtractedStructure:
    tempo_bpm: float
    time_signature: str
    num_bars: int
    tonic_pc: int
    mode: str
    scale_pitch_classes: Set[int]
    center_pitch: float
    melody_part_index: int
