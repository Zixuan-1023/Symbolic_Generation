/*
  ==============================================================================

    This file contains the basic framework code for a JUCE plugin processor.

  ==============================================================================
*/

#include "PluginProcessor.h"
#include "PluginEditor.h"

//==============================================================================
ControlableSymbolicMusicAudioProcessor::ControlableSymbolicMusicAudioProcessor()
#ifndef JucePlugin_PreferredChannelConfigurations
     : AudioProcessor (BusesProperties()
                     #if ! JucePlugin_IsMidiEffect
                      #if ! JucePlugin_IsSynth
                       .withInput  ("Input",  juce::AudioChannelSet::stereo(), true)
                      #endif
                       .withOutput ("Output", juce::AudioChannelSet::stereo(), true)
                     #endif
                       )
#endif
{
}

ControlableSymbolicMusicAudioProcessor::~ControlableSymbolicMusicAudioProcessor()
{
    stopTimer();
}

//==============================================================================
const juce::String ControlableSymbolicMusicAudioProcessor::getName() const
{
    return JucePlugin_Name;
}

bool ControlableSymbolicMusicAudioProcessor::acceptsMidi() const
{
   #if JucePlugin_WantsMidiInput
    return true;
   #else
    return false;
   #endif
}

bool ControlableSymbolicMusicAudioProcessor::producesMidi() const
{
   #if JucePlugin_ProducesMidiOutput
    return true;
   #else
    return false;
   #endif
}

bool ControlableSymbolicMusicAudioProcessor::isMidiEffect() const
{
   #if JucePlugin_IsMidiEffect
    return true;
   #else
    return false;
   #endif
}

double ControlableSymbolicMusicAudioProcessor::getTailLengthSeconds() const
{
    return 0.0;
}

int ControlableSymbolicMusicAudioProcessor::getNumPrograms()
{
    return 1;   // NB: some hosts don't cope very well if you tell them there are 0 programs,
                // so this should be at least 1, even if you're not really implementing programs.
}

int ControlableSymbolicMusicAudioProcessor::getCurrentProgram()
{
    return 0;
}

void ControlableSymbolicMusicAudioProcessor::setCurrentProgram (int index)
{
}

const juce::String ControlableSymbolicMusicAudioProcessor::getProgramName (int index)
{
    return {};
}

void ControlableSymbolicMusicAudioProcessor::changeProgramName (int index, const juce::String& newName)
{
}

//==============================================================================
void ControlableSymbolicMusicAudioProcessor::prepareToPlay (double sampleRate, int samplesPerBlock)
{
    // Use this method as the place to do any pre-playback
    // initialisation that you need..
}

void ControlableSymbolicMusicAudioProcessor::releaseResources()
{
    // When playback stops, you can use this as an opportunity to free up any
    // spare memory, etc.
}

#ifndef JucePlugin_PreferredChannelConfigurations
bool ControlableSymbolicMusicAudioProcessor::isBusesLayoutSupported (const BusesLayout& layouts) const
{
  #if JucePlugin_IsMidiEffect
    juce::ignoreUnused (layouts);
    return true;
  #else
    // This is the place where you check if the layout is supported.
    // In this template code we only support mono or stereo.
    // Some plugin hosts, such as certain GarageBand versions, will only
    // load plugins that support stereo bus layouts.
    if (layouts.getMainOutputChannelSet() != juce::AudioChannelSet::mono()
     && layouts.getMainOutputChannelSet() != juce::AudioChannelSet::stereo())
        return false;

    // This checks if the input layout matches the output layout
   #if ! JucePlugin_IsSynth
    if (layouts.getMainOutputChannelSet() != layouts.getMainInputChannelSet())
        return false;
   #endif

    return true;
  #endif
}
#endif

void ControlableSymbolicMusicAudioProcessor::processBlock (juce::AudioBuffer<float>& buffer, juce::MidiBuffer& midiMessages)
{
    juce::ScopedNoDenormals noDenormals;
    auto totalNumInputChannels  = getTotalNumInputChannels();
    auto totalNumOutputChannels = getTotalNumOutputChannels();

    // In case we have more outputs than inputs, this code clears any output
    // channels that didn't contain input data, (because these aren't
    // guaranteed to be empty - they may contain garbage).
    // This is here to avoid people getting screaming feedback
    // when they first compile a plugin, but obviously you don't need to keep
    // this code if your algorithm always overwrites all the output channels.
    for (auto i = totalNumInputChannels; i < totalNumOutputChannels; ++i)
        buffer.clear (i, 0, buffer.getNumSamples());

    // This is the place where you'd normally do the guts of your plugin's
    // audio processing...
    // Make sure to reset the state if your inner loop is processing
    // the samples and the outer loop is handling the channels.
    // Alternatively, you can process the samples with the channels
    // interleaved by keeping the same state.
    for (int channel = 0; channel < totalNumInputChannels; ++channel)
    {
        auto* channelData = buffer.getWritePointer (channel);
        juce::ignoreUnused (channelData);

        // ..do something to the data...
    }
}

//==============================================================================
bool ControlableSymbolicMusicAudioProcessor::hasEditor() const
{
    return true; // (change this to false if you choose to not supply an editor)
}

juce::AudioProcessorEditor* ControlableSymbolicMusicAudioProcessor::createEditor()
{
    return new ControlableSymbolicMusicAudioProcessorEditor (*this);
}

//==============================================================================
void ControlableSymbolicMusicAudioProcessor::getStateInformation (juce::MemoryBlock& destData)
{
    // You should use this method to store your parameters in the memory block.
    // You could do that either as raw data, or use the XML or ValueTree classes
    // as intermediaries to make it easy to save and load complex data.
}

void ControlableSymbolicMusicAudioProcessor::setStateInformation (const void* data, int sizeInBytes)
{
    // You should use this method to restore your parameters from this memory block,
    // whose contents will have been created by the getStateInformation() call.
}

void ControlableSymbolicMusicAudioProcessor::submitGenerate(const juce::String& requestJson)
{
    if (requestInFlight.exchange(true))
        return;

    juce::Logger::writeToLog("submitGenerate called");
    juce::Logger::writeToLog("REQUEST JSON:\n" + requestJson);

    updateJobState([&](JobSnapshot& state)
    {
        state.state = "running";
        state.jobId.clear();
        state.midiPath.clear();
        state.errorMessage.clear();
        state.message.clear();
        state.progress = 0;
        state.usedControls = juce::var();
        state.finalAttrs = juce::var();
    });

    client.postGenerate(requestJson, [this](juce::var resp, juce::String err)
    {
        requestInFlight = false;

        juce::Logger::writeToLog("postGenerate err=" + err);
        juce::Logger::writeToLog("postGenerate resp=" + juce::JSON::toString(resp, true));

        if (err.containsIgnoreCase("Code=-999") || err.containsIgnoreCase("cancelled"))
            return;

        if (err.isNotEmpty())
        {
            updateJobState([&](JobSnapshot& state)
            {
                state.state = "error";
                state.errorMessage = err;
                state.message = err;
            });
            return;
        }

        auto jobId = resp.getProperty("job_id", "").toString();
        juce::Logger::writeToLog("job_id=" + jobId);
        auto message = resp.getProperty("message", "").toString();
        updateJobState([&](JobSnapshot& state)
        {
            state.state = "running";
            state.jobId = jobId;
            state.message = message;
        });

        if (jobId.isNotEmpty())
            startTimer(pollIntervalMs);
        else
            updateJobState([&](JobSnapshot& state)
            {
                state.state = "error";
                state.errorMessage = "Missing job_id";
            });
    });
}

ControlableSymbolicMusicAudioProcessor::JobSnapshot ControlableSymbolicMusicAudioProcessor::getLastJobSnapshot() const
{
    std::lock_guard<std::mutex> lock(jobMutex);
    return jobState;
}

void ControlableSymbolicMusicAudioProcessor::setBackendBaseUrl(juce::String baseUrl)
{
    client.setBaseUrl(std::move(baseUrl));
}

juce::String ControlableSymbolicMusicAudioProcessor::getBackendBaseUrl() const
{
    return client.getBaseUrl();
}

void ControlableSymbolicMusicAudioProcessor::setEditorPrompt(juce::String prompt)
{
    std::lock_guard<std::mutex> lock(editorUiMutex);
    editorPrompt = std::move(prompt);
}

juce::String ControlableSymbolicMusicAudioProcessor::getEditorPrompt() const
{
    std::lock_guard<std::mutex> lock(editorUiMutex);
    return editorPrompt;
}

void ControlableSymbolicMusicAudioProcessor::setEditorMidiPath(juce::String midiPath)
{
    std::lock_guard<std::mutex> lock(editorUiMutex);
    editorMidiPath = std::move(midiPath);
}

juce::String ControlableSymbolicMusicAudioProcessor::getEditorMidiPath() const
{
    std::lock_guard<std::mutex> lock(editorUiMutex);
    return editorMidiPath;
}

void ControlableSymbolicMusicAudioProcessor::setEditorMode(juce::String mode)
{
    std::lock_guard<std::mutex> lock(editorUiMutex);
    editorMode = std::move(mode);
}

juce::String ControlableSymbolicMusicAudioProcessor::getEditorMode() const
{
    std::lock_guard<std::mutex> lock(editorUiMutex);
    return editorMode;
}

void ControlableSymbolicMusicAudioProcessor::timerCallback()
{
    juce::String jobId;
    {
        std::lock_guard<std::mutex> lock(jobMutex);
        jobId = jobState.jobId;
    }

    if (jobId.isEmpty())
        return;
    if (pollInFlight.exchange(true))
        return;

    auto jobIdCopy = jobId;
    client.getJob(jobIdCopy, [this, jobIdCopy](juce::var job, juce::String err)
    {
        pollInFlight = false;

        juce::Logger::writeToLog("getJob err=" + err);
        juce::Logger::writeToLog("getJob resp=" + juce::JSON::toString(job, true));

        if (err.containsIgnoreCase("Code=-999") || err.containsIgnoreCase("cancelled"))
            return;

        if (err.isNotEmpty())
        {
            updateJobState([&](JobSnapshot& state)
            {
                state.state = "error";
                state.errorMessage = err;
            });
            stopTimer();
            return;
        }

        auto status = job.getProperty("status", "").toString();
        auto message = job.getProperty("message", "").toString();
        juce::Logger::writeToLog("JOB status=" + status);
        if (status == "running" || status == "queued" || status == "accepted")
        {
            auto rawProgressVar = job.getProperty("progress", 0.0);
            double p = rawProgressVar.isDouble() ? (double) rawProgressVar
                                                 : (double) (int) rawProgressVar;
            if (p > 0.0 && p <= 1.0)
                p *= 100.0;
            auto progress = (int) juce::jlimit(0.0, 100.0, p);
            updateJobState([&](JobSnapshot& state)
            {
                state.state = "running";
                state.progress = progress;
                state.message = message;
            });
        }
        else if (status == "done")
        {
            stopTimer();
            auto midiPath = juce::String();
            auto midiUrl = juce::String();

            midiPath = job.getProperty("midi_path", "").toString();
            midiUrl = job.getProperty("midiUrl", "").toString();
            if (midiUrl.isEmpty())
                midiUrl = job.getProperty("midi_url", "").toString();

            auto result = job.getProperty("result", juce::var());
            if (midiPath.isEmpty())
                midiPath = result.getProperty("midi_path", "").toString();
            if (midiUrl.isEmpty())
                midiUrl = result.getProperty("midi_url", "").toString();

            if (midiPath.isEmpty() || midiUrl.isEmpty())
            {
                auto vars = job.getProperty("variations", juce::var()).getArray();
                if (vars != nullptr && vars->size() > 0)
                {
                    auto v0 = vars->getReference(0);
                    if (midiPath.isEmpty())
                        midiPath = v0.getProperty("midi_path", "").toString();
                    if (midiUrl.isEmpty())
                        midiUrl = v0.getProperty("midi_url", "").toString();
                }
            }

            if (midiPath.isEmpty() || midiUrl.isEmpty())
            {
                auto primary = job.getProperty("primaryVariation", juce::var());
                if (midiPath.isEmpty())
                    midiPath = primary.getProperty("midi_path", "").toString();
                if (midiUrl.isEmpty())
                    midiUrl = primary.getProperty("midi_url", "").toString();
                if (midiUrl.isEmpty())
                    midiUrl = primary.getProperty("midiUrl", "").toString();
            }

            auto localMidiPath = juce::String();
            auto needsDownload = true;
            if (midiPath.isNotEmpty())
            {
                juce::File f(midiPath);
                DBG("MIDI PATH: " + midiPath);
                DBG("exists=" + juce::String(f.existsAsFile() ? "1" : "0")
                    + " size=" + juce::String(f.getSize()));
                if (f.existsAsFile())
                {
                    localMidiPath = midiPath;
                    needsDownload = false;
                }
            }

            updateJobState([&](JobSnapshot& state)
            {
                state.state = "done";
                state.midiPath = localMidiPath;
                state.message = message;
                state.usedControls = job.getProperty("used_controls", juce::var());
                state.finalAttrs = job.getProperty("final_attrs", juce::var());
            });

            if (! needsDownload)
                return;

            auto startDownload = [this](const juce::String& url)
            {
                updateJobState([&](JobSnapshot& state)
                {
                    state.message = "Downloading MIDI...";
                });

                auto retryCount = std::make_shared<int>(0);
                auto downloader = std::make_shared<std::function<void()>>();
                *downloader = [this, url, retryCount, downloader]()
                {
                    client.downloadFile(url, [this, url, retryCount, downloader](juce::File file, juce::String err)
                    {
                        if (err.containsIgnoreCase("cancelled") && *retryCount < 1)
                        {
                            (*retryCount)++;
                            (*downloader)();
                            return;
                        }

                        if (err.isNotEmpty())
                        {
                            updateJobState([&](JobSnapshot& state)
                            {
                                state.state = "error";
                                state.errorMessage = err;
                                state.message = err;
                            });
                            return;
                        }

                        updateJobState([&](JobSnapshot& state)
                        {
                            state.midiPath = file.getFullPathName();
                            state.message = "MIDI downloaded";
                        });
                    });
                };
                (*downloader)();
            };

            if (midiUrl.isNotEmpty())
            {
                startDownload(midiUrl);
            }
            else if (jobIdCopy.isNotEmpty())
            {
                startDownload("/v1/jobs/" + jobIdCopy + "/midi");
            }
        }
        else if (status == "error")
        {
            stopTimer();
            updateJobState([&](JobSnapshot& state)
            {
                state.state = "error";
                state.errorMessage = message;
                state.message = message;
            });
        }
    });
}

void ControlableSymbolicMusicAudioProcessor::updateJobState(std::function<void(JobSnapshot&)> fn)
{
    std::lock_guard<std::mutex> lock(jobMutex);
    fn(jobState);
}

//==============================================================================
// This creates new instances of the plugin..
juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter()
{
    return new ControlableSymbolicMusicAudioProcessor();
}
