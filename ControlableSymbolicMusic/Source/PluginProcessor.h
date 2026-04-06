/*
  ==============================================================================

    This file contains the basic framework code for a JUCE plugin processor.

  ==============================================================================
*/

#pragma once

#include <JuceHeader.h>
#include "BackendClient.h"
#include <mutex>

//==============================================================================
/**
*/
class ControlableSymbolicMusicAudioProcessor  : public juce::AudioProcessor, private juce::Timer
{
public:
    //==============================================================================
    ControlableSymbolicMusicAudioProcessor();
    ~ControlableSymbolicMusicAudioProcessor() override;

    //==============================================================================
    void prepareToPlay (double sampleRate, int samplesPerBlock) override;
    void releaseResources() override;

   #ifndef JucePlugin_PreferredChannelConfigurations
    bool isBusesLayoutSupported (const BusesLayout& layouts) const override;
   #endif

    void processBlock (juce::AudioBuffer<float>&, juce::MidiBuffer&) override;

    //==============================================================================
    juce::AudioProcessorEditor* createEditor() override;
    bool hasEditor() const override;

    //==============================================================================
    const juce::String getName() const override;

    bool acceptsMidi() const override;
    bool producesMidi() const override;
    bool isMidiEffect() const override;
    double getTailLengthSeconds() const override;

    //==============================================================================
    int getNumPrograms() override;
    int getCurrentProgram() override;
    void setCurrentProgram (int index) override;
    const juce::String getProgramName (int index) override;
    void changeProgramName (int index, const juce::String& newName) override;

    //==============================================================================
    void getStateInformation (juce::MemoryBlock& destData) override;
    void setStateInformation (const void* data, int sizeInBytes) override;

    struct JobSnapshot
    {
        juce::String state; // idle/running/done/error
        int progress = 0;   // 0-100
        juce::String jobId;
        juce::String midiPath;      // optional
        juce::String errorMessage;  // optional
        juce::String message;       // optional
        juce::var usedControls;     // optional
        juce::var finalAttrs;       // optional
    };

    void submitGenerate(const juce::String& requestJson);
    JobSnapshot getLastJobSnapshot() const;
    void setBackendBaseUrl(juce::String baseUrl);
    juce::String getBackendBaseUrl() const;
    void setEditorPrompt(juce::String prompt);
    juce::String getEditorPrompt() const;
    void setEditorMidiPath(juce::String midiPath);
    juce::String getEditorMidiPath() const;
    void setEditorMode(juce::String mode);
    juce::String getEditorMode() const;

private:
    void timerCallback() override;
    void updateJobState(std::function<void(JobSnapshot&)> fn);

    BackendClient client { "https://mustang-licence-shipped-firms.trycloudflare.com" };
    std::atomic<bool> requestInFlight { false };
    std::atomic<bool> pollInFlight { false };
    int pollIntervalMs = 500;

    mutable std::mutex jobMutex;
    JobSnapshot jobState;

    mutable std::mutex editorUiMutex;
    juce::String editorPrompt;
    juce::String editorMidiPath;
    juce::String editorMode { "new" };

    //==============================================================================
    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (ControlableSymbolicMusicAudioProcessor)
};
