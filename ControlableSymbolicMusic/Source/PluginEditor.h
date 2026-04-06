/*
  ==============================================================================

    This file contains the basic framework code for a JUCE plugin editor.

  ==============================================================================
*/

#pragma once

#include <JuceHeader.h>
#include "PluginProcessor.h"
#include "ThemeLookAnd Feel.h"
//==============================================================================
/**
*/

// class MidiPreviewComponent;

enum class UiState{
    Idle,
    Generating,
    Success,
    Error
};

enum class GenMode{
    New,
    Continue,
    Transformation
};

struct RequestData{
    juce::String prompt;
    GenMode mode = GenMode::New;

    // MuseCoco attributes
    juce::String instrument = "Piano";
    juce::String key = "C:maj";
    float tempo = 0.5f;
    juce::String timeSignature = "4/4";
    juce::String phraseLength = "medium";
    int bars = 4; // compatibility field derived from phrase length
    int maxLenTokens = 1024;
    int minLenTokens = 819;
    float danceability = 0.5f;
    float rhythmIntensity = 0.5f;

    // AR-VAE controls (0..1 normalized)
    float rhyComplexity = 0.5f;
    float pitchRange = 0.5f;
    float noteDensity = 0.5f;
    float contour = 0.5f;

    juce::String midiPath;
    int seed = 0;
};

class MidiRollComponent : public juce::Component
{
public:
    void setSequence(juce::MidiMessageSequence seq);
    void setTiming(double bpm, int beatsPerBar);
    void setDragMidiPath(const juce::String& path);
    void paint(juce::Graphics& g) override;
    void mouseDown(const juce::MouseEvent& e) override;

private:
    bool isBlackKey(int midiNote) const;
    juce::String noteLabel(int midiNote) const;

    juce::MidiMessageSequence sequence;
    double lengthSeconds = 0.0;
    int minNote = 0;
    int maxNote = 127;
    int pianoWidth = 60;
    double tempoBpm = 120.0;
    int beatsPerBar = 4;
    juce::String dragMidiPath;
};

class ControlableSymbolicMusicAudioProcessorEditor  : public juce::AudioProcessorEditor,
                                                      private juce::Timer,
                                                      public juce::FileDragAndDropTarget,
                                                      public juce::DragAndDropContainer
{
public:
    ControlableSymbolicMusicAudioProcessorEditor (ControlableSymbolicMusicAudioProcessor&);
    ~ControlableSymbolicMusicAudioProcessorEditor() override;

    //==============================================================================
    void paint (juce::Graphics&) override;
    void resized() override;
    bool isInterestedInFileDrag (const juce::StringArray& files) override;
    void filesDropped (const juce::StringArray& files, int x, int y) override;

private:
    // This reference is provided as a quick way for your editor to
    // access the processor object that created it.
    
    // ---------- Timer (Polling) ----------
    void timerCallback() override;

    // ---------- State Controller ----------
    void setUiState(UiState newState, juce::String errorMsg = {});
    void beginGenerate();
    void pollJobOnce();
    void applyJobResult(const juce::var& jobJson);
    bool loadTestMidi();
    bool loadMidiFromPath(const juce::String& path);
    void updateModeButtons();
    void updateControlVisibility();

    // ---------- Protocol ----------
    RequestData snapshotRequestData() const;
    juce::String buildRequestJson(const RequestData& req) const;

    // ---------- Processor ----------
    ControlableSymbolicMusicAudioProcessor& audioProcessor;
    // juce::AudioProcessorValueTreeState& apvts;
    
    // ---------- View Components ----------
    // std::unique_ptr<MidiPreviewComponent> midiPreview;
    MidiRollComponent midiPreview;

    juce::TextEditor promptEditor;
    juce::Label refinePromptLabel;

    juce::ComboBox instrumentBox;
    juce::ComboBox keyBox;
    juce::ComboBox tempoBox;
    juce::ComboBox timeSignatureBox;
    juce::ComboBox phraseLengthBox;
    juce::Slider danceabilitySlider;
    juce::Slider rhythmIntensitySlider;

    juce::Slider arRhyComplexitySlider;
    juce::Slider arPitchRangeSlider;
    juce::Slider arNoteDensitySlider;
    juce::Slider arContourSlider;

    juce::ToggleButton modeNewButton { "New" };
    juce::ToggleButton modeContinueButton { "Continue" };
    juce::ToggleButton modeRefineButton { "Transformation" };

    juce::TextButton generateButton { "Generate" };
    juce::TextButton clearMidiButton { "Clear MIDI" };
    juce::TextEditor serverEditor;
    juce::TextButton applyServerButton { "Apply" };
    juce::Label statusLabel;

    juce::Label refinementSectionLabel;

    juce::Label instrumentLabel;
    juce::Label keyLabel;
    juce::Label tempoLabel;
    juce::Label timeSignatureLabel;
    juce::Label phraseLengthLabel;
    juce::Label danceabilityLabel;
    juce::Label rhythmIntensityLabel;

    juce::Label arRhyComplexityLabel;
    juce::Label arPitchRangeLabel;
    juce::Label arNoteDensityLabel;
    juce::Label arContourLabel;
    juce::Label arRhyComplexityHelp;
    juce::Label arPitchRangeHelp;
    juce::Label arNoteDensityHelp;
    juce::Label arContourHelp;

    // ---------- Glue: Attachments ----------
    using SliderAttachment = juce::AudioProcessorValueTreeState::SliderAttachment;
    using ButtonAttachment = juce::AudioProcessorValueTreeState::ButtonAttachment;

    std::unique_ptr<SliderAttachment> attRhythmDensity;
    std::unique_ptr<SliderAttachment> attTempo;
    std::unique_ptr<SliderAttachment> attEnergy;
    std::unique_ptr<SliderAttachment> attPitchRange;
    std::unique_ptr<SliderAttachment> attPolyphony;
    
    // Theme and Look
    ThemeLookAndFeel theme;

    // Mode attachments are optional:
    // - if mode is NOT a processor parameter, do not attach; store in UI only.
    // - if you want host automation for mode, then attach.
    // std::unique_ptr<ButtonAttachment> attModeNew;
    // ...

    // ---------- Job / Networking State ----------
    UiState uiState { UiState::Idle };
    juce::String lastError;


    juce::MidiFile loadedMidi;
    juce::MidiMessageSequence loadedSequence;
    juce::String droppedMidiPath;
    juce::String lastLoadedMidiPath;
    GenMode lastMode = GenMode::New;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (ControlableSymbolicMusicAudioProcessorEditor)
};
