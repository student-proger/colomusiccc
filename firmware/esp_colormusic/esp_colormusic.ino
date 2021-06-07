/////////////////////////////////////////////////////////////////
// Author:         Gladyshev Dmitriy (2021)
//
// Create Date:    
// Design Name:    
// Target Devices: ESP8266
// Tool versions:  Arduino IDE 1.8.13 + ESP8266 2.7.4
// Description:    
// Version:        1.0
/////////////////////////////////////////////////////////////////

#include <ESP8266WiFi.h>
#include <WiFiClient.h>
#include <WiFiUdp.h>

const char *ssid = "colormusic";
const char *password = "1234567890";

const byte chan[] = {16, 5, 4, 0};
const byte led[] = {13, 12, 14, 2};

bool state[] = {false, false, false, false};

unsigned int localPort = 8888;
char packetBuffer[UDP_TX_PACKET_MAX_SIZE + 1];

WiFiUDP Udp;

IPAddress local_IP(192, 168, 10, 100);
IPAddress gateway(192, 168, 10, 1);
IPAddress subnet(255, 255, 255, 0);

//Время последнего приёма пакета данных
unsigned long lastRX = 0;

void setup()
{
  for (int i = 0; i < 4; i++)
  {
    pinMode(chan[i], OUTPUT);
    pinMode(led[i], OUTPUT);
    digitalWrite(chan[i], LOW);
    digitalWrite(led[i], HIGH);
  }

  delay(1000);
  Serial.begin(115200);

  if (!WiFi.config(local_IP, gateway, subnet)) {
    Serial.println("STA Failed to configure");
  }
  

  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);

  while (WiFi.status() != WL_CONNECTED) {
    for (int i = 0; i < 4; i++)
    {
      digitalWrite(led[i], HIGH);
    }
    delay(300);
    for (int i = 0; i < 4; i++)
    {
      digitalWrite(led[i], LOW);
    }
    delay(300);
    Serial.print(".");
  }
  for (int i = 0; i < 4; i++)
  {
    digitalWrite(led[i], HIGH);
  }

  Udp.begin(localPort);
}

void refresh()
{
  for (int i = 0; i < 4; i++)
  {
    if (state[i])
    {
      digitalWrite(chan[i], HIGH);
      digitalWrite(led[i], LOW);
    }
    else
    {
      digitalWrite(chan[i], LOW);
      digitalWrite(led[i], HIGH);
    }
  }
}

void loop()
{
  int packetSize = Udp.parsePacket();
  if (packetSize) 
  {
    int n = Udp.read(packetBuffer, UDP_TX_PACKET_MAX_SIZE);
    if (n == 4)
    {
      lastRX = millis();
      for (int i = 0; i < 4; i++)
      {
        if (packetBuffer[i] == '1')
        {
          state[i] = true;
        }
        else
        {
          state[i] = false;
        }
      }
    }
  }

  //Гасим лампы, если больше 5 секунд нет пакетов
  if (millis() - lastRX > 5000)
  {
    for (int i = 0; i < 4; i++)
    {
      state[i] = false;
    }
  }

  //Защита от превышения тока
  if (state[0] && state[1] && state[2] && state[3])
  {
    state[3] = false;
  }

  refresh();
  
  while (Serial.available() > 0)
  {
    Serial.read();
  }
}
