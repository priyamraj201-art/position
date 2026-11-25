#pragma once

/**
 * Example Hardware and Network Configuration for ESP32-C3 Shelf-Light Beacon
 * Copy this file to config.local.h to configure local Wi-Fi credentials.
 * config.local.h is git-ignored and will not be committed.
 */

#ifndef WIFI_SSID
#define WIFI_SSID "YOUR_WIFI_SSID"
#endif

#ifndef WIFI_PASS
#define WIFI_PASS "YOUR_WIFI_PASSWORD"
#endif

#ifndef SERVER_HOST
#define SERVER_HOST "http://192.168.1.50:8000"
#endif

#ifndef DEVICE_ID
#define DEVICE_ID "shelf-light-01"
#endif

// Hardware GPIO pinout
#define LED_PIN 4
#define LED_COUNT 12
#define BUZZER_PIN 5
#define ONBOARD_LED_PIN 8

// Timing & Network Constants
#define LONG_POLL_WAIT_SEC 20
#define HTTP_CLIENT_TIMEOUT_MS 25000
#define BUZZER_FREQUENCY_HZ 2400
