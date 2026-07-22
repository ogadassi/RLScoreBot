#pragma once

#include "bakkesmod/plugin/bakkesmodplugin.h"
#include "bakkesmod/plugin/pluginwindow.h"
#include "bakkesmod/plugin/PluginSettingsWindow.h"

#include <string>
#include <memory>

class RLScoreBotClient : public BakkesMod::Plugin::BakkesModPlugin, public BakkesMod::Plugin::PluginSettingsWindow
{
public:
    virtual void onLoad() override;
    virtual void onUnload() override;

    // Plugin Settings UI
    void RenderSettings() override;
    std::string GetPluginName() override;
    void SetImGuiContext(uintptr_t ctx) override;

private:
    std::string apiToken = "";
    std::string serverUrl = "https://your-bot-domain.com";

    void OnGoalScored(std::string eventName);
    void SendGoalWebhook();
    void SaveConfig();
    void LoadConfig();
};
