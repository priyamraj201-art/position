#pragma once

#if __has_include("config.local.h")
#include "config.local.h"
#endif

/**
 * Hardware and Network Configuration for ESP32-C3 Shelf-Light Beacon
 * Wiring:
 *   ESP32-C3 GPIO4 -> 330 ohm resistor -> WS2812B DIN
 *   ESP32-C3 GPIO5 -> Passive Buzzer (+) -> Common GND
 *   5V / GND to LED strip with 1000 uF electrolytic capacitor across 5V & GND
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
