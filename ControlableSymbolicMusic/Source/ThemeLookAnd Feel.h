/*
  ==============================================================================

    ThemeLookAnd Feel.h
    Created: 3 Feb 2026 12:06:01pm
    Author:  Orca

  ==============================================================================
*/

#pragma once
#include <JuceHeader.h>

class ThemeLookAndFeel : public juce::LookAndFeel_V4{
    public:
    ThemeLookAndFeel(){
        setColour (juce::ResizableWindow::backgroundColourId, juce::Colour::fromRGB(18, 18, 20));
        setColour (juce::Label::textColourId, juce::Colours::white.withAlpha(0.85f));
        setColour (juce::TextEditor::textColourId, juce::Colours::white.withAlpha(0.9f));
        setColour (juce::TextEditor::backgroundColourId, juce::Colour::fromRGB(28, 28, 32));
        setColour (juce::TextEditor::outlineColourId, juce::Colours::transparentBlack);
        setColour (juce::TextEditor::highlightColourId, juce::Colour::fromRGB(80, 140, 190).withAlpha(0.35f));

        setColour (juce::Slider::trackColourId, juce::Colours::white.withAlpha(0.10f));
        setColour (juce::Slider::thumbColourId, juce::Colour::fromRGB(90, 170, 220));
        setColour (juce::Slider::rotarySliderFillColourId, juce::Colour::fromRGB(90, 170, 220));
        setColour (juce::Slider::textBoxTextColourId, juce::Colours::white.withAlpha(0.9f));
        setColour (juce::Slider::textBoxBackgroundColourId, juce::Colour::fromRGB(26, 28, 32));
        setColour (juce::Slider::textBoxOutlineColourId, juce::Colours::white.withAlpha(0.15f));

        setColour (juce::TextButton::buttonColourId, juce::Colour::fromRGB(40, 44, 50));
        setColour (juce::TextButton::buttonOnColourId, juce::Colour::fromRGB(55, 70, 85));
        setColour (juce::TextButton::textColourOffId, juce::Colours::white.withAlpha(0.9f));
        setColour (juce::TextButton::textColourOnId, juce::Colours::white.withAlpha(0.95f));

        setColour (juce::ToggleButton::textColourId, juce::Colours::white.withAlpha(0.85f));
        setColour (juce::ToggleButton::tickColourId, juce::Colour::fromRGB(90, 170, 220));
        setColour (juce::ToggleButton::tickDisabledColourId, juce::Colours::white.withAlpha(0.25f));
    }
    
    
    void drawButtonBackground (juce::Graphics& g, juce::Button& b,
                               const juce::Colour& backgroundColour,
                               bool isMouseOverButton, bool isButtonDown) override{
        auto r = b.getLocalBounds().toFloat().reduced(1.0f);
        auto base = backgroundColour;

        if (! b.isEnabled())
            base = base.darker(0.35f).withAlpha(0.7f);

        if (isButtonDown)   base = base.brighter(0.15f);
        else if (isMouseOverButton) base = base.brighter(0.08f);

        // subtle shadow
        if (b.isEnabled())
        {
            g.setColour (juce::Colours::black.withAlpha(0.25f));
            g.fillRoundedRectangle (r.translated(0, 1.5f), 10.0f);
        }

        g.setColour (base);
        g.fillRoundedRectangle (r, 10.0f);

        g.setColour (juce::Colours::white.withAlpha(b.isEnabled() ? 0.08f : 0.04f));
        g.drawRoundedRectangle (r, 10.0f, 1.0f);
    }

    void drawLinearSlider (juce::Graphics& g, int x, int y, int w, int h,
                           float sliderPos, float min, float max,
                           const juce::Slider::SliderStyle, juce::Slider& s) override{
        
        auto track = juce::Rectangle<float>((float)x, (float)y + h * 0.5f - 2.0f, (float)w, 4.0f);

        g.setColour (s.findColour(juce::Slider::trackColourId));
        g.fillRoundedRectangle (track, 2.0f);

        auto filled = track.withWidth (sliderPos - (float)x);
        g.setColour (juce::Colour::fromRGB(90, 170, 220).withAlpha(0.65f));
        g.fillRoundedRectangle (filled, 2.0f);

        // thumb
        g.setColour (s.findColour(juce::Slider::thumbColourId));
        g.fillEllipse (sliderPos - 6.0f, track.getCentreY() - 6.0f, 12.0f, 12.0f);
        g.setColour (juce::Colours::black.withAlpha(0.25f));
        g.drawEllipse (sliderPos - 6.0f, track.getCentreY() - 6.0f, 12.0f, 12.0f, 1.0f);
    }

    juce::Font getLabelFont(juce::Label&) override
    {
        return juce::Font (juce::FontOptions (13.5f));
    }

    juce::Font getTextButtonFont(juce::TextButton&, int buttonHeight) override
    {
        auto size = juce::jlimit (12.0f, 15.0f, buttonHeight * 0.55f);
        return juce::Font (juce::FontOptions (size).withStyle ("Bold"));
    }

    juce::Font getPopupMenuFont() override
    {
        return juce::Font (juce::FontOptions (13.0f));
    }
};
