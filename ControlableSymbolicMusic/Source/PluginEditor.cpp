/*
  ==============================================================================

    This file contains the basic framework code for a JUCE plugin editor.

  ==============================================================================
*/

#include "PluginProcessor.h"
#include "PluginEditor.h"

void MidiRollComponent::setSequence(juce::MidiMessageSequence seq)
{
    sequence = std::move(seq);
    sequence.updateMatchedPairs();

    lengthSeconds = 0.0;
    minNote = 127;
    maxNote = 0;

    for (int i = 0; i < sequence.getNumEvents(); ++i)
    {
        auto* ev = sequence.getEventPointer(i);
        if (ev == nullptr)
            continue;

        auto& msg = ev->message;
        lengthSeconds = juce::jmax(lengthSeconds, msg.getTimeStamp());

        if (msg.isNoteOn())
        {
            auto note = msg.getNoteNumber();
            minNote = juce::jmin(minNote, note);
            maxNote = juce::jmax(maxNote, note);
        }
    }

    if (minNote > maxNote)
    {
        minNote = 0;
        maxNote = 127;
    }

    repaint();
}

void MidiRollComponent::setTiming(double bpm, int beatsPerBar_)
{
    tempoBpm = (bpm > 0.0 ? bpm : 120.0);
    beatsPerBar = (beatsPerBar_ > 0 ? beatsPerBar_ : 4);
    repaint();
}

void MidiRollComponent::setDragMidiPath(const juce::String& path)
{
    dragMidiPath = path;
}

void MidiRollComponent::mouseDown(const juce::MouseEvent& e)
{
    juce::ignoreUnused(e);
    if (dragMidiPath.isEmpty())
        return;

    juce::File file(dragMidiPath);
    if (! file.existsAsFile())
        return;

    juce::StringArray files;
    files.add(file.getFullPathName());
    juce::DragAndDropContainer::performExternalDragDropOfFiles(files, false, this);
}

bool MidiRollComponent::isBlackKey(int midiNote) const
{
    switch (midiNote % 12)
    {
        case 1:
        case 3:
        case 6:
        case 8:
        case 10:
            return true;
        default:
            return false;
    }
}

juce::String MidiRollComponent::noteLabel(int midiNote) const
{
    static const char* names[] = { "C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B" };
    auto name = juce::String(names[midiNote % 12]);
    auto octave = (midiNote / 12) - 1;
    return name + juce::String(octave);
}

void MidiRollComponent::paint(juce::Graphics& g)
{
    auto area = getLocalBounds();
    g.fillAll(juce::Colour::fromRGB(24, 26, 30));

    if (lengthSeconds <= 0.0 || sequence.getNumEvents() == 0)
    {
        g.setColour(juce::Colours::white.withAlpha(0.25f));
        g.setFont(juce::FontOptions(14.0f));
        g.drawText("No MIDI loaded", area, juce::Justification::centred);
        return;
    }

    auto pianoArea = area.removeFromLeft(pianoWidth);
    auto rollArea = area;
    const auto height = rollArea.getHeight();
    const auto width = rollArea.getWidth();
    const auto noteRange = juce::jmax(1, maxNote - minNote + 1);

    g.setColour(juce::Colours::white.withAlpha(0.08f));
    for (int i = 0; i < noteRange; ++i)
    {
        auto y = rollArea.getY() + juce::roundToInt((float) (noteRange - 1 - i) * height / (float) noteRange);
        g.drawHorizontalLine(y, (float) rollArea.getX(), (float) rollArea.getRight());
    }

    // Beat grid (draw every beat, with stronger bar lines)
    const auto secPerBeat = 60.0 / tempoBpm;
    const auto totalBeats = juce::jmax(1, (int) std::ceil(lengthSeconds / secPerBeat));
    for (int b = 0; b <= totalBeats; ++b)
    {
        const auto x = (float) rollArea.getX()
                       + (float) ((b * secPerBeat) / lengthSeconds * (double) width);
        const bool barLine = (b % beatsPerBar) == 0;
        g.setColour(barLine ? juce::Colours::white.withAlpha(0.30f)
                            : juce::Colours::white.withAlpha(0.18f));

        g.drawLine(x, (float) rollArea.getY(), x, (float) rollArea.getBottom(),
                   barLine ? 2.0f : 1.0f);
    }

    // Piano roll background with key hints
    for (int i = 0; i < noteRange; ++i)
    {
        auto midiNote = maxNote - i;
        auto y = pianoArea.getY() + juce::roundToInt((float) i * height / (float) noteRange);
        auto h = juce::jmax(1, (int) juce::roundToInt((float) height / (float) noteRange));

        auto isBlack = isBlackKey(midiNote);
        g.setColour(isBlack ? juce::Colour::fromRGB(40, 42, 48)
                            : juce::Colour::fromRGB(70, 72, 78));
        g.fillRect(pianoArea.getX(), y, pianoArea.getWidth(), h);

        if (! isBlack && (midiNote % 12 == 0))
        {
            g.setColour(juce::Colours::white.withAlpha(0.6f));
            g.setFont(juce::FontOptions(11.0f));
            g.drawText(noteLabel(midiNote), pianoArea.reduced(4, 0).withY(y).withHeight(h),
                       juce::Justification::centredLeft);
        }
    }

    g.setColour(juce::Colours::white.withAlpha(0.2f));
    g.drawRect(pianoArea);

    g.setColour(juce::Colour::fromRGB(110, 180, 255));
    for (int i = 0; i < sequence.getNumEvents(); ++i)
    {
        auto* ev = sequence.getEventPointer(i);
        if (ev == nullptr)
            continue;

        auto& msg = ev->message;
        if (! msg.isNoteOn())
            continue;

        auto* off = ev->noteOffObject;
        if (off == nullptr)
            continue;

        auto start = msg.getTimeStamp();
        auto end = off->message.getTimeStamp();
        if (end <= start)
            continue;

        auto note = msg.getNoteNumber();
        auto x = rollArea.getX() + (int) juce::roundToInt(start / lengthSeconds * width);
        auto w = juce::jmax(1, (int) juce::roundToInt((end - start) / lengthSeconds * width));
        auto y = rollArea.getY() + (int) juce::roundToInt((float) (maxNote - note) * height / (float) noteRange);
        auto h = juce::jmax(1, (int) juce::roundToInt((float) height / (float) noteRange));

        g.fillRect(x, y, w, h);
    }
}

//==============================================================================
ControlableSymbolicMusicAudioProcessorEditor::ControlableSymbolicMusicAudioProcessorEditor (ControlableSymbolicMusicAudioProcessor& p)
    : AudioProcessorEditor (&p), audioProcessor (p)
{
    // Make sure that before the constructor has finished, you've set the
    // editor's size to whatever you need it to be.
    setSize (900, 600);
    setLookAndFeel(&theme);
    addAndMakeVisible(midiPreview);

    promptEditor.setMultiLine(true);
    promptEditor.setReturnKeyStartsNewLine(true);
    promptEditor.setTextToShowWhenEmpty("Type your prompt here...", juce::Colours::white.withAlpha(0.35f));
    promptEditor.setIndents(10, 8);
    promptEditor.setColour(juce::TextEditor::shadowColourId, juce::Colours::transparentBlack);
    promptEditor.setFont(juce::Font (juce::FontOptions (15.0f)));
    promptEditor.onTextChange = [this]
    {
        audioProcessor.setEditorPrompt(promptEditor.getText());
    };
    addAndMakeVisible(promptEditor);

    refinePromptLabel.setText("Not used in Transformation mode", juce::dontSendNotification);
    refinePromptLabel.setColour(juce::Label::textColourId, juce::Colours::white.withAlpha(0.45f));
    refinePromptLabel.setJustificationType(juce::Justification::centred);
    addAndMakeVisible(refinePromptLabel);

    auto configureSlider = [this](juce::Slider& slider, juce::Label& label, const juce::String& name,
                                   double min, double max, double step, double value)
    {
        slider.setSliderStyle(juce::Slider::LinearHorizontal);
        slider.setTextBoxStyle(juce::Slider::TextBoxRight, false, 60, 20);
        slider.setRange(min, max, step);
        slider.setValue(value);
        addAndMakeVisible(slider);

        label.setText(name, juce::dontSendNotification);
        label.attachToComponent(&slider, true);
        addAndMakeVisible(label);
    };

    refinementSectionLabel.setText("Transformation Controls", juce::dontSendNotification);
    refinementSectionLabel.setColour(juce::Label::textColourId, juce::Colours::white.withAlpha(0.7f));
    addAndMakeVisible(refinementSectionLabel);

    instrumentBox.addItem("Piano", 1);
    instrumentBox.addItem("Strings", 2);
    instrumentBox.addItem("Guitar", 3);
    instrumentBox.addItem("Bass", 4);
    instrumentBox.addItem("Drums", 5);
    instrumentBox.setSelectedId(1);
    addAndMakeVisible(instrumentBox);
    instrumentLabel.setText("Instrument", juce::dontSendNotification);
    instrumentLabel.attachToComponent(&instrumentBox, true);
    addAndMakeVisible(instrumentLabel);

    keyBox.addItem("C:maj", 1);
    keyBox.addItem("G:maj", 2);
    keyBox.addItem("D:maj", 3);
    keyBox.addItem("A:maj", 4);
    keyBox.addItem("E:maj", 5);
    keyBox.addItem("B:maj", 6);
    keyBox.addItem("F#:maj", 7);
    keyBox.addItem("C#:maj", 8);
    keyBox.addItem("F:maj", 9);
    keyBox.addItem("Bb:maj", 10);
    keyBox.addItem("Eb:maj", 11);
    keyBox.addItem("Ab:maj", 12);
    keyBox.addItem("Db:maj", 13);
    keyBox.addItem("Gb:maj", 14);
    keyBox.addItem("Cb:maj", 15);
    keyBox.addItem("A:min", 16);
    keyBox.addItem("E:min", 17);
    keyBox.addItem("B:min", 18);
    keyBox.addItem("F#:min", 19);
    keyBox.addItem("C#:min", 20);
    keyBox.addItem("G#:min", 21);
    keyBox.addItem("D#:min", 22);
    keyBox.addItem("A#:min", 23);
    keyBox.addItem("D:min", 24);
    keyBox.addItem("G:min", 25);
    keyBox.addItem("C:min", 26);
    keyBox.addItem("F:min", 27);
    keyBox.addItem("Bb:min", 28);
    keyBox.addItem("Eb:min", 29);
    keyBox.addItem("Ab:min", 30);
    keyBox.setSelectedId(1);
    addAndMakeVisible(keyBox);
    keyLabel.setText("Key", juce::dontSendNotification);
    keyLabel.attachToComponent(&keyBox, true);
    addAndMakeVisible(keyLabel);

    tempoBox.addItem("Slow", 1);
    tempoBox.addItem("Medium", 2);
    tempoBox.addItem("Fast", 3);
    tempoBox.setSelectedId(2);
    addAndMakeVisible(tempoBox);
    tempoLabel.setText("Tempo", juce::dontSendNotification);
    tempoLabel.attachToComponent(&tempoBox, true);
    addAndMakeVisible(tempoLabel);

    timeSignatureBox.addItem("4/4", 1);
    timeSignatureBox.addItem("3/4", 2);
    timeSignatureBox.addItem("6/8", 3);
    timeSignatureBox.setSelectedId(1);
    addAndMakeVisible(timeSignatureBox);
    timeSignatureLabel.setText("Time Signature", juce::dontSendNotification);
    timeSignatureLabel.attachToComponent(&timeSignatureBox, true);
    addAndMakeVisible(timeSignatureLabel);

    phraseLengthBox.addItem("Short (2-4 bars)", 1);
    phraseLengthBox.addItem("Medium (4-8 bars)", 2);
    phraseLengthBox.addItem("Long (8-16 bars)", 3);
    phraseLengthBox.setSelectedId(2);
    addAndMakeVisible(phraseLengthBox);
    phraseLengthLabel.setText("Phrase Length", juce::dontSendNotification);
    phraseLengthLabel.attachToComponent(&phraseLengthBox, true);
    addAndMakeVisible(phraseLengthLabel);

    configureSlider(danceabilitySlider, danceabilityLabel, "Danceability", 0.0, 1.0, 0.001, 0.5);
    configureSlider(rhythmIntensitySlider, rhythmIntensityLabel, "Rhythm Intensity", 0.0, 1.0, 0.001, 0.5);

    configureSlider(arRhyComplexitySlider, arRhyComplexityLabel, "Rhythm Complexity", 0.0, 1.0, 0.001, 0.5);
    configureSlider(arPitchRangeSlider, arPitchRangeLabel, "Pitch Range", 0.0, 1.0, 0.001, 0.5);
    configureSlider(arNoteDensitySlider, arNoteDensityLabel, "Note Density", 0.0, 1.0, 0.001, 0.5);
    configureSlider(arContourSlider, arContourLabel, "Contour", 0.0, 1.0, 0.001, 0.5);

    auto configureHelp = [this](juce::Label& label, const juce::String& text)
    {
        label.setText(text, juce::dontSendNotification);
        label.setColour(juce::Label::textColourId, juce::Colours::white.withAlpha(0.45f));
        label.setFont(juce::Font(juce::FontOptions(11.0f)));
        addAndMakeVisible(label);
    };

    configureHelp(arRhyComplexityHelp, "simpler <-> more varied rhythm");
    configureHelp(arPitchRangeHelp, "narrower <-> wider melodic range");
    configureHelp(arNoteDensityHelp, "fewer <-> more notes");
    configureHelp(arContourHelp, "flatter <-> more shaped motion");

    modeNewButton.setRadioGroupId(1);
    modeContinueButton.setRadioGroupId(1);
    modeRefineButton.setRadioGroupId(1);
    modeNewButton.setClickingTogglesState(true);
    modeContinueButton.setClickingTogglesState(true);
    modeRefineButton.setClickingTogglesState(true);
    modeNewButton.setToggleState(true, juce::dontSendNotification);

    addAndMakeVisible(modeNewButton);
    addAndMakeVisible(modeContinueButton);
    addAndMakeVisible(modeRefineButton);
    modeNewButton.onClick = [this]
    {
        audioProcessor.setEditorMode("new");
        updateControlVisibility();
    };
    modeContinueButton.onClick = [this]
    {
        audioProcessor.setEditorMode("continue");
        updateControlVisibility();
    };
    modeRefineButton.onClick = [this]
    {
        audioProcessor.setEditorMode("transformation");
        updateControlVisibility();
    };
    updateModeButtons();
    updateControlVisibility();

    generateButton.onClick = [this]
    {
        beginGenerate();
    };
    generateButton.setColour(juce::TextButton::buttonColourId, juce::Colour::fromRGB(45, 60, 75));
    generateButton.setColour(juce::TextButton::buttonOnColourId, juce::Colour::fromRGB(60, 90, 115));
    addAndMakeVisible(generateButton);

    clearMidiButton.onClick = [this]
    {
        droppedMidiPath.clear();
        audioProcessor.setEditorMidiPath({});
        lastLoadedMidiPath.clear();
        loadedMidi.clear();
        loadedSequence.clear();
        midiPreview.setSequence(juce::MidiMessageSequence());
        midiPreview.repaint();
        statusLabel.setText("MIDI cleared", juce::dontSendNotification);
        updateModeButtons();
        updateControlVisibility();
    };
    addAndMakeVisible(clearMidiButton);

    serverEditor.setText(audioProcessor.getBackendBaseUrl());
    serverEditor.setSelectAllWhenFocused(true);
    serverEditor.setColour(juce::TextEditor::backgroundColourId, juce::Colour::fromRGB(28, 28, 32));
    serverEditor.setColour(juce::TextEditor::outlineColourId, juce::Colours::white.withAlpha(0.2f));
    addAndMakeVisible(serverEditor);

    applyServerButton.onClick = [this]
    {
        auto input = serverEditor.getText().trim();
        if (input.isEmpty())
            return;

        juce::String baseUrl = input;
        if (! baseUrl.startsWithIgnoreCase("http"))
        {
            auto colonCount = input.retainCharacters(":").length();
            if (baseUrl.startsWithChar('['))
                baseUrl = "http://" + baseUrl;
            else if (colonCount > 1)
                baseUrl = "http://[" + baseUrl + "]:8000";
            else if (baseUrl.containsChar(':'))
                baseUrl = "http://" + baseUrl;
            else
                baseUrl = "http://" + baseUrl + ":8000";
        }

        audioProcessor.setBackendBaseUrl(baseUrl);
        serverEditor.setText(audioProcessor.getBackendBaseUrl(), juce::dontSendNotification);
        statusLabel.setText("Server set: " + baseUrl, juce::dontSendNotification);
    };
    addAndMakeVisible(applyServerButton);

    statusLabel.setText("Idle (UI only)", juce::dontSendNotification);
    statusLabel.setColour(juce::Label::textColourId, juce::Colours::white.withAlpha(0.7f));
    addAndMakeVisible(statusLabel);

    promptEditor.setText(audioProcessor.getEditorPrompt(), juce::dontSendNotification);
    droppedMidiPath = audioProcessor.getEditorMidiPath();
    if (droppedMidiPath.isNotEmpty() && loadMidiFromPath(droppedMidiPath))
        lastLoadedMidiPath = droppedMidiPath;
    else
    {
        auto snapshot = audioProcessor.getLastJobSnapshot();
        if (snapshot.midiPath.isNotEmpty() && loadMidiFromPath(snapshot.midiPath))
            lastLoadedMidiPath = snapshot.midiPath;
    }

    auto mode = audioProcessor.getEditorMode();
    if (mode == "transformation" || mode == "refine")
        modeRefineButton.setToggleState(true, juce::dontSendNotification);
    else if (mode == "continue")
        modeContinueButton.setToggleState(true, juce::dontSendNotification);
    else
        modeNewButton.setToggleState(true, juce::dontSendNotification);
    updateModeButtons();
    updateControlVisibility();
}

ControlableSymbolicMusicAudioProcessorEditor::~ControlableSymbolicMusicAudioProcessorEditor()
{
    setLookAndFeel(nullptr);
}

//==============================================================================
void ControlableSymbolicMusicAudioProcessorEditor::paint (juce::Graphics& g)
{
    // (Our component is opaque, so we must completely fill the background with a solid colour)
    g.fillAll (juce::Colour::fromRGB (20, 20, 22));

    g.setColour (juce::Colours::white.withAlpha (0.9f));
    g.setFont (juce::FontOptions (15.0f));
    g.drawText ("Controllable Symbolic Music Generator",
                   20, 10, getWidth() - 40, 28,
                   juce::Justification::centredLeft);
    // Draw section frames (debug layout helper)
    auto bounds = getLocalBounds().reduced (16);
    auto midiArea = bounds.removeFromTop (int (bounds.getHeight() * 0.35f));
    bounds.removeFromTop (10);
    auto bottomArea = bounds;

    auto gap = 10;
    auto totalWidth = bottomArea.getWidth();
    auto promptWidth = int (totalWidth * 0.30f);
    auto actionsWidth = juce::jmax (170, int (totalWidth * 0.20f));
    auto controlsWidth = totalWidth - promptWidth - actionsWidth - gap * 2;
    if (controlsWidth < 200)
        controlsWidth = 200;

    auto promptArea = bottomArea.removeFromLeft (promptWidth);
    bottomArea.removeFromLeft (gap);
    auto actionsArea = bottomArea.removeFromRight (actionsWidth);
    bottomArea.removeFromRight (gap);
    auto controlsArea = bottomArea.withTrimmedLeft (0).withWidth (controlsWidth);

    auto drawCard = [&g](juce::Rectangle<int> area)
    {
        auto bounds = area.toFloat();
        g.setColour (juce::Colour::fromRGB (30, 30, 34));
        g.fillRoundedRectangle (bounds, 10.0f);
        g.setColour (juce::Colours::white.withAlpha (0.12f));
        g.drawRoundedRectangle (bounds, 10.0f, 1.0f);
    };

    drawCard(midiArea);
    drawCard(promptArea);
    drawCard(controlsArea);
    drawCard(actionsArea);

    // Section labels
    g.setColour (juce::Colours::white.withAlpha (0.35f));
    g.setFont (juce::FontOptions (14.0f));
    g.drawText ("MIDI Preview / Drop Zone", midiArea.reduced(12).removeFromTop(20),
                   juce::Justification::centredLeft);

    g.drawText ("Prompt", promptArea.reduced(12).removeFromTop(20),
                   juce::Justification::centredLeft);

    g.drawText ("Controls", controlsArea.reduced(12).removeFromTop(20),
                   juce::Justification::centredLeft);

    g.drawText ("Actions", actionsArea.reduced(12).removeFromTop(20),
                   juce::Justification::centredLeft);
}



void ControlableSymbolicMusicAudioProcessorEditor::resized()
{
    // This is generally where you'll want to lay out the positions of any
    // subcomponents in your editor..
    auto bounds = getLocalBounds().reduced (16);

    auto midiArea = bounds.removeFromTop (int (bounds.getHeight() * 0.35f));
    bounds.removeFromTop (10);

    auto bottomArea = bounds;

    auto gap = 10;
    auto totalWidth = bottomArea.getWidth();
    auto promptWidth = int (totalWidth * 0.30f);
    auto actionsWidth = juce::jmax (170, int (totalWidth * 0.20f));
    auto controlsWidth = totalWidth - promptWidth - actionsWidth - gap * 2;
    if (controlsWidth < 200)
        controlsWidth = 200;

    auto promptArea = bottomArea.removeFromLeft (promptWidth);
    bottomArea.removeFromLeft (gap);
    auto actionsArea = bottomArea.removeFromRight (actionsWidth);
    bottomArea.removeFromRight (gap);
    auto controlsArea = bottomArea.withTrimmedLeft (0).withWidth (controlsWidth);

    midiPreview.setBounds(midiArea);
    auto promptContent = promptArea.reduced(12, 28);
    promptEditor.setBounds(promptContent);
    refinePromptLabel.setBounds(promptContent);

    auto actionsContent = actionsArea.reduced(12, 28);
    auto modeRowHeight = 24;
    modeNewButton.setBounds(actionsContent.removeFromTop(modeRowHeight));
    actionsContent.removeFromTop(6);
    modeContinueButton.setBounds(actionsContent.removeFromTop(modeRowHeight));
    actionsContent.removeFromTop(6);
    modeRefineButton.setBounds(actionsContent.removeFromTop(modeRowHeight));
    actionsContent.removeFromTop(12);
    generateButton.setBounds(actionsContent.removeFromTop(32));
    actionsContent.removeFromTop(8);
    clearMidiButton.setBounds(actionsContent.removeFromTop(28));
    actionsContent.removeFromTop(8);
    serverEditor.setBounds(actionsContent.removeFromTop(26));
    actionsContent.removeFromTop(6);
    applyServerButton.setBounds(actionsContent.removeFromTop(24));
    actionsContent.removeFromTop(8);
    statusLabel.setBounds(actionsContent.removeFromTop(24));

    auto controlsContent = controlsArea.reduced(12, 24);
    auto rowHeight = 24;
    auto rowGap = 12;
    auto labelWidth = 120;

    auto layoutSliderRow = [&](juce::Label& label, juce::Slider& slider)
    {
        if (! slider.isVisible())
            return;
        auto row = controlsContent.removeFromTop(rowHeight);
        label.setSize(labelWidth, rowHeight);
        slider.setBounds(row.withTrimmedLeft(labelWidth));
        controlsContent.removeFromTop(rowGap);
    };

    auto layoutHelpRow = [&](juce::Label& label)
    {
        if (! label.isVisible())
            return;
        auto row = controlsContent.removeFromTop(18);
        label.setBounds(row.withTrimmedLeft(labelWidth));
        controlsContent.removeFromTop(rowGap);
    };

    auto layoutComboRow = [&](juce::Label& label, juce::ComboBox& box)
    {
        if (! box.isVisible())
            return;
        auto row = controlsContent.removeFromTop(rowHeight);
        label.setSize(labelWidth, rowHeight);
        box.setBounds(row.withTrimmedLeft(labelWidth));
        controlsContent.removeFromTop(rowGap);
    };

    // Generation section title removed

    layoutComboRow(instrumentLabel, instrumentBox);
    layoutComboRow(keyLabel, keyBox);
    layoutComboRow(tempoLabel, tempoBox);
    layoutComboRow(timeSignatureLabel, timeSignatureBox);
    layoutComboRow(phraseLengthLabel, phraseLengthBox);
    layoutSliderRow(danceabilityLabel, danceabilitySlider);
    layoutSliderRow(rhythmIntensityLabel, rhythmIntensitySlider);

    if (refinementSectionLabel.isVisible())
    {
        controlsContent.removeFromTop(rowGap);
        refinementSectionLabel.setBounds(controlsContent.removeFromTop(18));
        controlsContent.removeFromTop(8);
    }

    layoutSliderRow(arRhyComplexityLabel, arRhyComplexitySlider);
    layoutHelpRow(arRhyComplexityHelp);
    layoutSliderRow(arPitchRangeLabel, arPitchRangeSlider);
    layoutHelpRow(arPitchRangeHelp);
    layoutSliderRow(arNoteDensityLabel, arNoteDensitySlider);
    layoutHelpRow(arNoteDensityHelp);
    layoutSliderRow(arContourLabel, arContourSlider);
    layoutHelpRow(arContourHelp);
}

void ControlableSymbolicMusicAudioProcessorEditor::timerCallback()
{
    auto snapshot = audioProcessor.getLastJobSnapshot();
    updateModeButtons();
    updateControlVisibility();
    generateButton.setEnabled(snapshot.state != "running");

    if (snapshot.errorMessage.isNotEmpty())
    {
        statusLabel.setText("Error: " + snapshot.errorMessage, juce::dontSendNotification);
        stopTimer();
        return;
    }

    if (snapshot.midiPath.isNotEmpty() && snapshot.midiPath != lastLoadedMidiPath)
    {
        if (loadMidiFromPath(snapshot.midiPath))
            lastLoadedMidiPath = snapshot.midiPath;
    }

    midiPreview.setDragMidiPath(snapshot.midiPath);

    if (snapshot.state == "idle")
    {
        statusLabel.setText("Idle", juce::dontSendNotification);
    }
    else if (snapshot.state == "running" && snapshot.jobId.isEmpty())
    {
        statusLabel.setText("Sending...", juce::dontSendNotification);
    }
    else if (snapshot.state == "running")
    {
        juce::String text("Generating...");
        statusLabel.setText(text, juce::dontSendNotification);
    }
    else if (snapshot.state == "done")
    {
        if (snapshot.midiPath.isEmpty())
        {
            juce::String text("Done (downloading MIDI)...");
            statusLabel.setText(text, juce::dontSendNotification);
        }
        else
        {
            juce::String text = juce::String("Done: ") + snapshot.midiPath;
            if (snapshot.message.isNotEmpty())
            {
                text += juce::String(" | ");
                text += snapshot.message;
            }
            statusLabel.setText(text, juce::dontSendNotification);
            stopTimer();
        }
    }
}

void ControlableSymbolicMusicAudioProcessorEditor::updateControlVisibility()
{
    auto isRefine = modeRefineButton.getToggleState();
    auto currentMode = isRefine ? GenMode::Transformation
                                : (modeContinueButton.getToggleState() ? GenMode::Continue : GenMode::New);
    if (currentMode == GenMode::Transformation && lastMode != GenMode::Transformation)
    {
        arRhyComplexitySlider.setValue(0.5, juce::dontSendNotification);
        arPitchRangeSlider.setValue(0.5, juce::dontSendNotification);
        arNoteDensitySlider.setValue(0.5, juce::dontSendNotification);
        arContourSlider.setValue(0.5, juce::dontSendNotification);
    }
    lastMode = currentMode;

    auto showGeneration = ! isRefine;
    auto controlsEnabled = currentMode == GenMode::New;
    instrumentBox.setVisible(showGeneration);
    keyBox.setVisible(showGeneration);
    tempoBox.setVisible(showGeneration);
    timeSignatureBox.setVisible(showGeneration);
    phraseLengthBox.setVisible(showGeneration);
    danceabilitySlider.setVisible(showGeneration);
    rhythmIntensitySlider.setVisible(showGeneration);
    instrumentLabel.setVisible(showGeneration);
    keyLabel.setVisible(showGeneration);
    tempoLabel.setVisible(showGeneration);
    timeSignatureLabel.setVisible(showGeneration);
    phraseLengthLabel.setVisible(showGeneration);
    danceabilityLabel.setVisible(showGeneration);
    rhythmIntensityLabel.setVisible(showGeneration);
    promptEditor.setVisible(showGeneration);
    refinePromptLabel.setVisible(! showGeneration);
    promptEditor.setEnabled(currentMode == GenMode::New);

    refinementSectionLabel.setVisible(isRefine);

    arRhyComplexitySlider.setVisible(isRefine);
    arPitchRangeSlider.setVisible(isRefine);
    arNoteDensitySlider.setVisible(isRefine);
    arContourSlider.setVisible(isRefine);

    arRhyComplexityLabel.setVisible(isRefine);
    arPitchRangeLabel.setVisible(isRefine);
    arNoteDensityLabel.setVisible(isRefine);
    arContourLabel.setVisible(isRefine);
    arRhyComplexityHelp.setVisible(isRefine);
    arPitchRangeHelp.setVisible(isRefine);
    arNoteDensityHelp.setVisible(isRefine);
    arContourHelp.setVisible(isRefine);

    instrumentBox.setEnabled(controlsEnabled);
    keyBox.setEnabled(controlsEnabled);
    tempoBox.setEnabled(controlsEnabled);
    timeSignatureBox.setEnabled(controlsEnabled);
    phraseLengthBox.setEnabled(controlsEnabled);
    danceabilitySlider.setEnabled(controlsEnabled);
    rhythmIntensitySlider.setEnabled(controlsEnabled);

    resized();
}

bool ControlableSymbolicMusicAudioProcessorEditor::isInterestedInFileDrag (const juce::StringArray& files)
{
    for (auto& f : files)
        if (f.endsWithIgnoreCase(".mid") || f.endsWithIgnoreCase(".midi"))
            return true;
    return false;
}

void ControlableSymbolicMusicAudioProcessorEditor::filesDropped (const juce::StringArray& files, int x, int y)
{
    juce::ignoreUnused(x, y);
    for (auto& f : files)
    {
        if (f.endsWithIgnoreCase(".mid") || f.endsWithIgnoreCase(".midi"))
        {
            droppedMidiPath = f;
            audioProcessor.setEditorMidiPath(droppedMidiPath);
            loadMidiFromPath(f);
            statusLabel.setText("MIDI: " + juce::File(f).getFileName(), juce::dontSendNotification);
            updateModeButtons();
            break;
        }
    }
}

void ControlableSymbolicMusicAudioProcessorEditor::setUiState(UiState newState, juce::String errorMsg)
{
    uiState = newState;
    lastError = errorMsg;

    switch (uiState)
    {
        case UiState::Idle:
            statusLabel.setText("Idle (UI only)", juce::dontSendNotification);
            break;
        case UiState::Generating:
            statusLabel.setText("Generating... (stub)", juce::dontSendNotification);
            break;
        case UiState::Success:
            statusLabel.setText("Done (stub)", juce::dontSendNotification);
            break;
        case UiState::Error:
            statusLabel.setText("Error: " + lastError, juce::dontSendNotification);
            break;
    }
}

void ControlableSymbolicMusicAudioProcessorEditor::beginGenerate()
{
    auto request = snapshotRequestData();
    if ((request.mode == GenMode::Continue || request.mode == GenMode::Transformation) && request.midiPath.isEmpty())
    {
        statusLabel.setText("Please drop a MIDI file first", juce::dontSendNotification);
        return;
    }
    auto requestJson = buildRequestJson(request);
    juce::Logger::writeToLog("Editor beginGenerate");
    juce::Logger::writeToLog("REQUEST JSON:\n" + requestJson);
    audioProcessor.submitGenerate(requestJson);
    generateButton.setEnabled(false);
    startTimer(250);
}

void ControlableSymbolicMusicAudioProcessorEditor::pollJobOnce()
{
}

void ControlableSymbolicMusicAudioProcessorEditor::applyJobResult(const juce::var& jobJson)
{
    juce::ignoreUnused(jobJson);
}

bool ControlableSymbolicMusicAudioProcessorEditor::loadTestMidi()
{
    auto midiFile = juce::File::getCurrentWorkingDirectory()
                        .getChildFile("Backend/musecoco/runs/test_midi/Descending Major.mid");

    if (! midiFile.existsAsFile())
    {
        auto desktop = juce::File::getSpecialLocation(juce::File::userDesktopDirectory);
        auto fallback = desktop.getChildFile(
            "Thesis in Music Technology II/Thesis_Project/Backend/musecoco/runs/test_midi/Descending Major.mid");
        if (fallback.existsAsFile())
            midiFile = fallback;
    }

    if (! midiFile.existsAsFile())
    {
        statusLabel.setText("Test MIDI not found", juce::dontSendNotification);
        DBG("Test MIDI not found: " + midiFile.getFullPathName());
        return false;
    }

    juce::FileInputStream in(midiFile);
    if (! in.openedOk())
    {
        statusLabel.setText("Failed to open test MIDI", juce::dontSendNotification);
        DBG("Failed to open test MIDI: " + midiFile.getFullPathName());
        return false;
    }

    juce::MidiFile midi;
    if (! midi.readFrom(in))
    {
        statusLabel.setText("Failed to read test MIDI", juce::dontSendNotification);
        DBG("Failed to read test MIDI: " + midiFile.getFullPathName());
        return false;
    }

    midi.convertTimestampTicksToSeconds();
    loadedMidi = std::move(midi);

    auto bpm = 120.0;
    auto beatsPerBar = 4;
    for (int i = 0; i < loadedMidi.getNumTracks(); ++i)
    {
        auto* track = loadedMidi.getTrack(i);
        if (track == nullptr)
            continue;

        for (int e = 0; e < track->getNumEvents(); ++e)
        {
            auto* ev = track->getEventPointer(e);
            if (ev == nullptr)
                continue;
            auto& msg = ev->message;
            if (msg.isTempoMetaEvent())
                bpm = 60.0 / msg.getTempoSecondsPerQuarterNote();
            if (msg.isTimeSignatureMetaEvent())
            {
                int numerator = 4;
                int denominator = 4;
                msg.getTimeSignatureInfo(numerator, denominator);
                if (numerator > 0)
                    beatsPerBar = numerator;
            }
        }
    }

    juce::MidiMessageSequence seq;
    for (int i = 0; i < loadedMidi.getNumTracks(); ++i)
        seq.addSequence(*loadedMidi.getTrack(i), 0.0, 0.0, loadedMidi.getLastTimestamp());
    seq.updateMatchedPairs();
    loadedSequence = std::move(seq);
    midiPreview.setSequence(loadedSequence);
    midiPreview.setTiming(bpm, beatsPerBar);

    statusLabel.setText("Loaded test MIDI", juce::dontSendNotification);
    DBG("Loaded test MIDI: " + midiFile.getFullPathName()
        + " tracks=" + juce::String(loadedMidi.getNumTracks())
        + " lengthSec=" + juce::String(loadedMidi.getLastTimestamp(), 2));
    return true;
}

bool ControlableSymbolicMusicAudioProcessorEditor::loadMidiFromPath(const juce::String& path)
{
    juce::File midiFile(path);
    if (! midiFile.existsAsFile())
    {
        statusLabel.setText("MIDI not found", juce::dontSendNotification);
        DBG("MIDI not found: " + midiFile.getFullPathName());
        return false;
    }

    juce::FileInputStream in(midiFile);
    if (! in.openedOk())
    {
        statusLabel.setText("Failed to open MIDI", juce::dontSendNotification);
        DBG("Failed to open MIDI: " + midiFile.getFullPathName());
        return false;
    }

    juce::MidiFile midi;
    if (! midi.readFrom(in))
    {
        statusLabel.setText("Failed to read MIDI", juce::dontSendNotification);
        DBG("Failed to read MIDI: " + midiFile.getFullPathName());
        return false;
    }

    midi.convertTimestampTicksToSeconds();
    loadedMidi = std::move(midi);

    auto bpm = 120.0;
    auto beatsPerBar = 4;
    for (int i = 0; i < loadedMidi.getNumTracks(); ++i)
    {
        auto* track = loadedMidi.getTrack(i);
        if (track == nullptr)
            continue;

        for (int e = 0; e < track->getNumEvents(); ++e)
        {
            auto* ev = track->getEventPointer(e);
            if (ev == nullptr)
                continue;
            auto& msg = ev->message;
            if (msg.isTempoMetaEvent())
                bpm = 60.0 / msg.getTempoSecondsPerQuarterNote();
            if (msg.isTimeSignatureMetaEvent())
            {
                int numerator = 4;
                int denominator = 4;
                msg.getTimeSignatureInfo(numerator, denominator);
                if (numerator > 0)
                    beatsPerBar = numerator;
            }
        }
    }

    juce::MidiMessageSequence seq;
    for (int i = 0; i < loadedMidi.getNumTracks(); ++i)
        seq.addSequence(*loadedMidi.getTrack(i), 0.0, 0.0, loadedMidi.getLastTimestamp());
    seq.updateMatchedPairs();
    loadedSequence = std::move(seq);
    midiPreview.setSequence(loadedSequence);
    midiPreview.setTiming(bpm, beatsPerBar);

    DBG("Loaded MIDI: " + midiFile.getFullPathName()
        + " tracks=" + juce::String(loadedMidi.getNumTracks())
        + " lengthSec=" + juce::String(loadedMidi.getLastTimestamp(), 2));
    return true;
}

void ControlableSymbolicMusicAudioProcessorEditor::updateModeButtons()
{
    auto hasMidi = droppedMidiPath.isNotEmpty() || lastLoadedMidiPath.isNotEmpty();
    if (hasMidi)
    {
        modeNewButton.setToggleState(false, juce::dontSendNotification);
        if (! modeContinueButton.getToggleState() && ! modeRefineButton.getToggleState())
            modeContinueButton.setToggleState(true, juce::dontSendNotification);
        modeNewButton.setEnabled(false);
        modeContinueButton.setEnabled(true);
        modeRefineButton.setEnabled(true);
    }
    else
    {
        modeContinueButton.setToggleState(false, juce::dontSendNotification);
        modeRefineButton.setToggleState(false, juce::dontSendNotification);
        modeNewButton.setToggleState(true, juce::dontSendNotification);
        modeNewButton.setEnabled(true);
        modeContinueButton.setEnabled(false);
        modeRefineButton.setEnabled(false);
    }
}

RequestData ControlableSymbolicMusicAudioProcessorEditor::snapshotRequestData() const
{
    RequestData data;
    data.prompt = promptEditor.getText();
    auto instrumentText = instrumentBox.getText().toLowerCase();
    if (instrumentText.contains("piano")) data.instrument = "piano";
    else if (instrumentText.contains("string")) data.instrument = "strings";
    else if (instrumentText.contains("guitar")) data.instrument = "guitar";
    else if (instrumentText.contains("bass")) data.instrument = "bass";
    else if (instrumentText.contains("drum")) data.instrument = "drums";
    else data.instrument = instrumentText;
    data.key = keyBox.getText();
    auto tempoId = tempoBox.getSelectedId();
    if (tempoId == 1)
        data.tempo = 0.25f;
    else if (tempoId == 3)
        data.tempo = 0.75f;
    else
        data.tempo = 0.5f;
    data.timeSignature = timeSignatureBox.getText();
    auto lengthId = phraseLengthBox.getSelectedId();
    if (lengthId == 1)
    {
        data.phraseLength = "short";
        data.maxLenTokens = 512;
        data.minLenTokens = 410;
        data.bars = 4;
    }
    else if (lengthId == 3)
    {
        data.phraseLength = "long";
        data.maxLenTokens = 2048;
        data.minLenTokens = 1638;
        data.bars = 8;
    }
    else
    {
        data.phraseLength = "medium";
        data.maxLenTokens = 1024;
        data.minLenTokens = 819;
        data.bars = 6;
    }
    data.danceability = static_cast<float>(danceabilitySlider.getValue());
    data.rhythmIntensity = static_cast<float>(rhythmIntensitySlider.getValue());

    data.rhyComplexity = static_cast<float>(arRhyComplexitySlider.getValue());
    data.pitchRange = static_cast<float>(arPitchRangeSlider.getValue());
    data.noteDensity = static_cast<float>(arNoteDensitySlider.getValue());
    data.contour = static_cast<float>(arContourSlider.getValue());

    data.midiPath = droppedMidiPath.isNotEmpty() ? droppedMidiPath : lastLoadedMidiPath;
    data.seed = 0;

    if (modeContinueButton.getToggleState())
        data.mode = GenMode::Continue;
    else if (modeRefineButton.getToggleState())
        data.mode = GenMode::Transformation;
    else
        data.mode = GenMode::New;
    return data;
}

namespace
{
    juce::String fileToBase64(const juce::String& path)
    {
        juce::File file(path);
        if (! file.existsAsFile())
            return {};

        juce::FileInputStream in(file);
        if (! in.openedOk())
            return {};

        juce::MemoryBlock data;
        in.readIntoMemoryBlock(data);
        if (data.getSize() == 0)
            return {};

        return juce::Base64::toBase64(data.getData(), data.getSize());
    }
}

juce::String ControlableSymbolicMusicAudioProcessorEditor::buildRequestJson(const RequestData& req) const
{
    auto root = juce::DynamicObject::Ptr(new juce::DynamicObject());
    if (req.mode == GenMode::New)
        root->setProperty("prompt", req.prompt);

    juce::String modeString = "new";
    if (req.mode == GenMode::Continue)
        modeString = "continue";
    else if (req.mode == GenMode::Transformation)
        modeString = "transformation";
    root->setProperty("mode", modeString);

    if (req.mode == GenMode::New || req.mode == GenMode::Continue)
    {
        auto generation = juce::DynamicObject::Ptr(new juce::DynamicObject());
        generation->setProperty("phrase_length", req.phraseLength);
        generation->setProperty("instrument", req.instrument);
        generation->setProperty("key", req.key);
        generation->setProperty("tempo", req.tempo);
        generation->setProperty("time_signature", req.timeSignature);
        generation->setProperty("bars", req.bars);
        generation->setProperty("danceability", req.danceability);
        generation->setProperty("rhythm_intensity", req.rhythmIntensity);
        root->setProperty("generation", generation.get());
    }

    if (req.mode == GenMode::Transformation)
    {
        auto arvae = juce::DynamicObject::Ptr(new juce::DynamicObject());
        arvae->setProperty("rhy_complexity", req.rhyComplexity);
        arvae->setProperty("pitch_range", req.pitchRange);
        arvae->setProperty("note_density", req.noteDensity);
        arvae->setProperty("contour", req.contour);
        root->setProperty("arvae", arvae.get());
    }

    if (! req.midiPath.isEmpty())
    {
        auto midi = juce::DynamicObject::Ptr(new juce::DynamicObject());
        auto base64 = fileToBase64(req.midiPath);
        if (base64.isNotEmpty())
        {
            midi->setProperty("input_type", "base64");
            midi->setProperty("base64", base64);
        }
        else
        {
            midi->setProperty("input_type", "path");
            midi->setProperty("path", req.midiPath);
        }
        root->setProperty("midi", midi.get());
    }

    auto render = juce::DynamicObject::Ptr(new juce::DynamicObject());
    auto seed = req.seed;
    if (seed <= 0)
        seed = (int) (juce::Time::currentTimeMillis() & 0x7fffffff);
    render->setProperty("seed", seed);
    render->setProperty("max_len_b", req.maxLenTokens);
    render->setProperty("min_len", req.minLenTokens);
    render->setProperty("phrase_length", req.phraseLength);
    root->setProperty("render", render.get());

    return juce::JSON::toString(juce::var(root.get()));
}
