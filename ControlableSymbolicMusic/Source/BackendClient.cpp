/*
  ==============================================================================

    BackendClient.cpp
    Created: 7 Feb 2026 3:07:18pm
    Author:  Orca

  ==============================================================================
*/

#include "BackendClient.h"

namespace
{
    constexpr auto kGeneratePath = "/v1/generate";
    constexpr auto kJobsPath = "/v1/jobs/";
    constexpr auto kHealthPath = "/health";
}

BackendClient::BackendClient(juce::String baseUrl)
    : base(std::move(baseUrl))
{
    if (base.endsWithChar('/'))
        base = base.dropLastCharacters(1);
}

void BackendClient::setBaseUrl(juce::String baseUrl)
{
    base = std::move(baseUrl);
    if (base.endsWithChar('/'))
        base = base.dropLastCharacters(1);
}

juce::String BackendClient::getBaseUrl() const
{
    return base;
}

void BackendClient::getHealth(JsonCallback cb)
{
    runAsyncRequest(
        [this](juce::String& outErr) -> juce::String
        {
            auto url = juce::URL(base + kHealthPath);

            auto opts = juce::URL::InputStreamOptions(juce::URL::ParameterHandling::inAddress)
                            .withHttpRequestCmd("GET")
                            .withConnectionTimeoutMs(3000)
                            .withNumRedirectsToFollow(0);

            std::unique_ptr<juce::InputStream> in(url.createInputStream(opts));

            if (! in)
            {
                outErr = "GET /health failed (no stream)";
                return {};
            }

            return in->readEntireStreamAsString();
        },
        std::move(cb)
    );
}

void BackendClient::postGenerate(const juce::String& requestJson, JsonCallback cb)
{
    runAsyncRequest(
        [this, requestJson](juce::String& outErr) -> juce::String
        {
            auto url = juce::URL(base + kGeneratePath);
            juce::Logger::writeToLog("BackendClient POST: " + url.toString(true));
            juce::Logger::writeToLog("POST bytes=" + juce::String(requestJson.getNumBytesAsUTF8()));

            const juce::String extraHeaders =
                "Content-Type: application/json; charset=utf-8\r\n"
                "Accept: application/json\r\n";

            auto opts = juce::URL::InputStreamOptions(juce::URL::ParameterHandling::inAddress)
                            .withHttpRequestCmd("POST")
                            .withExtraHeaders(extraHeaders)
                            .withConnectionTimeoutMs(8000)
                            .withNumRedirectsToFollow(0);

            // JUCE 6: POST body goes on URL, not InputStreamOptions
            juce::MemoryBlock body(requestJson.toRawUTF8(),
                                   (size_t) requestJson.getNumBytesAsUTF8());
            url = url.withPOSTData(body);

            std::unique_ptr<juce::InputStream> in(url.createInputStream(opts));

            if (! in)
            {
                outErr = "POST /v1/generate failed (no stream)";
                return {};
            }

            return in->readEntireStreamAsString();
        },
        std::move(cb)
    );
}

void BackendClient::getJob(const juce::String& jobId, JsonCallback cb)
{
    runAsyncRequest(
        [this, jobId](juce::String& outErr) -> juce::String
        {
            auto url = juce::URL(base + kJobsPath + jobId);

            auto opts = juce::URL::InputStreamOptions(juce::URL::ParameterHandling::inAddress)
                            .withHttpRequestCmd("GET")
                            .withConnectionTimeoutMs(8000)
                            .withNumRedirectsToFollow(0);

            std::unique_ptr<juce::InputStream> in(url.createInputStream(opts));

            if (! in)
            {
                outErr = "GET /v1/jobs failed (no stream)";
                return {};
            }

            return in->readEntireStreamAsString();
        },
        std::move(cb)
    );
}

void BackendClient::downloadFile(const juce::String& relativeUrl, FileCallback cb)
{
    runAsyncBinaryRequest(
        [this, relativeUrl](juce::String& outErr) -> juce::MemoryBlock
        {
            auto url = relativeUrl.startsWithIgnoreCase("http") ? juce::URL(relativeUrl)
                                                                : juce::URL(base + relativeUrl);
            juce::Logger::writeToLog("BackendClient GET (file): " + url.toString(true));

            auto opts = juce::URL::InputStreamOptions(juce::URL::ParameterHandling::inAddress)
                            .withHttpRequestCmd("GET")
                            .withConnectionTimeoutMs(30000)
                            .withNumRedirectsToFollow(0);

            std::unique_ptr<juce::InputStream> in(url.createInputStream(opts));
            if (! in)
            {
                outErr = "GET " + relativeUrl + " failed (no stream)";
                return {};
            }

            juce::MemoryBlock data;
            in->readIntoMemoryBlock(data);
            return data;
        },
        std::move(cb)
    );
}

void BackendClient::runAsyncRequest(std::function<juce::String(juce::String& outErr)> doRequest,
                                   JsonCallback cb)
{
    // ThreadPool keeps async requests simple
    struct Job : public juce::ThreadPoolJob
    {
        std::function<juce::String(juce::String&)> fn;
        JsonCallback cb;

        Job(std::function<juce::String(juce::String&)> f, JsonCallback c)
        : juce::ThreadPoolJob("BackendClientJob"), fn(std::move(f)), cb(std::move(c)) {}

        JobStatus runJob() override
        {
            juce::String err;
            auto body = fn(err);

            juce::String parseErr;
            auto json = BackendClient::parseJsonOrNull(body, parseErr);

            if (err.isNotEmpty())
                parseErr = err;
            else if (parseErr.isNotEmpty())
                parseErr = "JSON parse error: " + parseErr + " | body=" + body;

            juce::MessageManager::callAsync([cb = std::move(cb), json, parseErr]()
            {
                cb(json, parseErr);
            });

            return jobHasFinished;
        }
    };

    static juce::ThreadPool pool(2);
    pool.addJob(new Job(std::move(doRequest), std::move(cb)), true);
}

void BackendClient::runAsyncBinaryRequest(std::function<juce::MemoryBlock(juce::String& outErr)> doRequest,
                                          FileCallback cb)
{
    struct Job : public juce::ThreadPoolJob
    {
        std::function<juce::MemoryBlock(juce::String&)> fn;
        FileCallback cb;

        Job(std::function<juce::MemoryBlock(juce::String&)> f, FileCallback c)
        : juce::ThreadPoolJob("BackendClientBinaryJob"), fn(std::move(f)), cb(std::move(c)) {}

        JobStatus runJob() override
        {
            juce::String err;
            auto data = fn(err);

            juce::File outFile;
            if (err.isEmpty())
            {
                outFile = juce::File::getSpecialLocation(juce::File::tempDirectory)
                              .getNonexistentChildFile("csm_job", ".mid", false);
                if (! outFile.replaceWithData(data.getData(), data.getSize()))
                    err = "Failed to write temp MIDI file";
            }

            juce::MessageManager::callAsync([cb = std::move(cb), outFile, err]()
            {
                cb(outFile, err);
            });

            return jobHasFinished;
        }
    };

    static juce::ThreadPool pool(2);
    pool.addJob(new Job(std::move(doRequest), std::move(cb)), true);
}

juce::var BackendClient::parseJsonOrNull(const juce::String& s, juce::String& err)
{
    if (s.isEmpty())
    {
        err = "Empty response";
        return {};
    }

    auto result = juce::JSON::parse(s);
    if (result.isVoid())
    {
        err = "JSON parse error";
        return {};
    }

    return result;
}
