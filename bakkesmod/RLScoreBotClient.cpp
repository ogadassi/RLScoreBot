#include "RLScoreBotClient.h"
#include "bakkesmod/wrappers/includes.h"
#include "bakkesmod/wrappers/cvarwrapper.h"

#include <curl/curl.h>
#include <thread>
#include <fstream>

BAKKESMOD_PLUGIN(RLScoreBotClient, "RLScoreBot Goal Telemetry Client", "2.0.0", PLUGINTYPE_FREEPLAY)

void RLScoreBotClient::onLoad()
{
    cvarManager->log("RLScoreBot Plugin loaded!");

    // Register CVar settings
    cvarManager->registerCvar("rlscorebot_token", "", "API Pairing Token from Discord /link", true);
    cvarManager->registerCvar("rlscorebot_server", "https://your-bot-domain.com", "RLScoreBot Server URL", true);

    // Hook into Rocket League Goal Event
    gameWrapper->HookEvent("Function TAGame.GFxHUD_TA.HandleStatTickerMessage", [this](std::string eventName) {
        OnGoalScored(eventName);
    });
}

void RLScoreBotClient::onUnload()
{
    cvarManager->log("RLScoreBot Plugin unloaded.");
}

void RLScoreBotClient::OnGoalScored(std::string eventName)
{
    cvarManager->log("Goal Event Detected in Rocket League! Triggering RLScoreBot Webhook...");
    std::thread([this]() {
        SendGoalWebhook();
    }).detach();
}

void RLScoreBotClient::SendGoalWebhook()
{
    std::string token = cvarManager->getCvar("rlscorebot_token").getStringValue();
    std::string baseUrl = cvarManager->getCvar("rlscorebot_server").getStringValue();

    if (token.empty()) {
        cvarManager->log("RLScoreBot Error: No API Token set. Run /link in Discord!");
        return;
    }

    std::string endpoint = baseUrl + "/api/v1/goal";
    std::string jsonPayload = "{\"api_token\":\"" + token + "\"}";

    CURL* curl = curl_easy_init();
    if (curl) {
        struct curl_slist* headers = NULL;
        headers = curl_slist_append(headers, "Content-Type: application/json");

        curl_easy_setopt(curl, CURLOPT_URL, endpoint.c_str());
        curl_easy_setopt(curl, CURLOPT_POSTFIELDS, jsonPayload.c_str());
        curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
        curl_easy_setopt(curl, CURLOPT_TIMEOUT, 3L);

        CURLcode res = curl_easy_perform(curl);
        if (res != CURLE_OK) {
            cvarManager->log("RLScoreBot Curl Failed: " + std::string(curl_easy_strerror(res)));
        } else {
            cvarManager->log("RLScoreBot Telemetry Sent Successfully!");
        }

        curl_easy_cleanup(curl);
        curl_slist_free_all(headers);
    }
}

void RLScoreBotClient::RenderSettings()
{
    // ImGui Plugin Settings Panel rendered inside BakkesMod F2 menu
}

std::string RLScoreBotClient::GetPluginName()
{
    return "RLScoreBot Client";
}

void RLScoreBotClient::SetImGuiContext(uintptr_t ctx)
{
}
