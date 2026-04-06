/*
  ==============================================================================

    BackendClient.h
    Created: 7 Feb 2026 3:06:59pm
    Author:  Orca

  ==============================================================================
*/

#pragma once
#include <JuceHeader.h>

class BackendClient
{
public:
    using JsonCallback = std::function<void (juce::var json, juce::String error)>;
    using FileCallback = std::function<void (juce::File file, juce::String error)>;

    explicit BackendClient(juce::String baseUrl);
    void setBaseUrl(juce::String baseUrl);
    juce::String getBaseUrl() const;

    // GET /health
    void getHealth(JsonCallback cb);

    // POST /v1/generate  -> { job_id: ... }
    void postGenerate(const juce::String& requestJson, JsonCallback cb);

    // GET /v1/jobs/{job_id} -> job json
    void getJob(const juce::String& jobId, JsonCallback cb);

    // GET binary file (e.g. /v1/jobs/{job_id}/midi)
    void downloadFile(const juce::String& relativeUrl, FileCallback cb);

private:
    juce::String base;
    void runAsyncRequest(std::function<juce::String(juce::String& outErr)> doRequest,
                         JsonCallback cb);
    void runAsyncBinaryRequest(std::function<juce::MemoryBlock(juce::String& outErr)> doRequest,
                               FileCallback cb);

    static juce::var parseJsonOrNull(const juce::String& s, juce::String& err);
};
