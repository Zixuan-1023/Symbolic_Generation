#pragma once
#include <JuceHeader.h>

namespace GenerationProtocol{

    const juce::String generateEndpoint = "http://127.0.0.1:8000/v1/generate";
    const juce::String jobStatusEndpoint = "http://127.0.0.1:8000/v1/jobs/";

    /*
    =======================
    Request Structure Example
    =======================

    {
      "prompt": "A happy cinematic piano intro",
      "context": {
        "bpm": 120,
        "time_signature": "4/4", // format: "x/y", default "4/4"
        "start_bar": 9,
        "length_bars": 8
      },
      "controls": {
        "hard": {
          "density": 0.8,    // float [0.0, 1.0]
          "tempo": 0.6,      // float [0.0, 1.0]
          "bass_energy": 0.2 // float [0.0, 1.0]
        },
        "soft": {
          "use_text2attr": true,
          "temperature": 1.0,
          "topk": 3
        },
        "constraints": {
          "key": "C:maj",
          "instrument_id": 0 // 0: Piano, 1: Strings, 2: Guitar, 3: Bass, 4: Drums
        }
      },
      "render": {
        "num_variations": 4,
        "seed": 1234,
        "format": "midi"
      }
    }

    =======================
    Response Example (Job Query)
    =======================

    {
      "status": "done",
      "variations": [
        {
          "name": "A",
          "midi_path": "/.../take_A.mid",
          "preview_path": "/.../take_A.preview.json"
        },
        {
          "name": "B",
          "midi_path": "/.../take_B.mid",
          "preview_path": "/.../take_B.preview.json"
        }
      ],
      "used_attributes": {
        "key": "C:maj",
        "tempo": "Fast"
      },
      "used_controls": {
        "density": 0.8,
        "tempo": 0.6,
        "bass_energy": 0.2
      },
      "seed": 1234
    }

    */

}
