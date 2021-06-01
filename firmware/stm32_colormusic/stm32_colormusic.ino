/*******************************************************************************
* Author:         Gladyshev Dmitriy (2020) 
* 
* Create Date:    25.05.2020  
* Design Name:    Цветомузыка
* Target Devices: STM32F103C8T6
* Tool versions:  Arduino IDE 
* Description:    Цветомузыка
* Version:        3.0 
*
* Parameters:     CPU Speed: 48 MHz
*                 Upload method: ST-Link
* 
*******************************************************************************/
#define DEVICE_VID 0x1EAF
#define DEVICE_PID 0x0028
#define DEVICE_MANUFACTURER "R0WBH"
#define DEVICE_PRODUCT "COLORMUSIC"
#define DEVICE_SERIAL "00001"

#include <USBComposite.h>

//Размеры буферов приёма/передачи USB HID
#define TXSIZE 2
#define RXSIZE 30

USBHID HID;
HIDRaw<TXSIZE,RXSIZE> raw(HID);
uint8_t rxbuf[RXSIZE];
uint8_t txbuf[TXSIZE];

uint16_t pwm[30];

uint16_t stepCounter = 0;
uint8_t DimSpeedValue;
uint8_t DimMode;

const uint8_t reportDescription[] = {
   HID_RAW_REPORT_DESCRIPTOR(TXSIZE,RXSIZE)
};

/******************************************************************************* 
* Function Name  : setup 
* Description    : setup
*******************************************************************************/

void setup(void)
{
  USBComposite.setVendorId(DEVICE_VID);
  USBComposite.setProductId(DEVICE_PID);
  USBComposite.setManufacturerString(DEVICE_MANUFACTURER);
  USBComposite.setProductString(DEVICE_PRODUCT);
  USBComposite.setSerialString(DEVICE_SERIAL);

  HID.begin(reportDescription, sizeof(reportDescription));  
  raw.begin();
  delay(3000);

  //Разрешаем использовать PB3/PB4
  //afio_cfg_debug_ports(AFIO_DEBUG_SW_ONLY);
  afio_cfg_debug_ports(AFIO_DEBUG_NONE);

  pinMode(PA0, OUTPUT);
  pinMode(PA1, OUTPUT);
  pinMode(PA2, OUTPUT);
  pinMode(PA3, OUTPUT);
  pinMode(PA4, OUTPUT);
  pinMode(PA5, OUTPUT);
  pinMode(PA6, OUTPUT);
  pinMode(PA7, OUTPUT);
  pinMode(PA8, OUTPUT);
  pinMode(PA9, OUTPUT);
  pinMode(PA10, OUTPUT);
  pinMode(PA13, OUTPUT);
  pinMode(PA14, OUTPUT);
  pinMode(PA15, OUTPUT);

  pinMode(PB0, OUTPUT);
  pinMode(PB1, OUTPUT);
  pinMode(PB2, OUTPUT);
  pinMode(PB3, OUTPUT);
  pinMode(PB4, OUTPUT);
  pinMode(PB5, OUTPUT);
  pinMode(PB6, OUTPUT);
  pinMode(PB7, OUTPUT);
  pinMode(PB8, OUTPUT);
  pinMode(PB9, OUTPUT);
  pinMode(PB10, OUTPUT);
  pinMode(PB11, OUTPUT);
  pinMode(PB12, OUTPUT);
  pinMode(PB13, OUTPUT);
  pinMode(PB14, OUTPUT);
  pinMode(PB15, OUTPUT);

}

/******************************************************************************* 
* Function Name  : loop 
* Description    : Главный цикл
*******************************************************************************/

void loop(void) 
{
  uint8_t buf[30];

  if (raw.getOutput(rxbuf))
  {
    for (int i = 0; i < TXSIZE; i++) txbuf[i] = 0x00;

    for (int i = 0; i < 30; i++) pwm[i] = rxbuf[i];
    
    



    raw.send(txbuf, TXSIZE);
  }

  for (int i = 0; i < 30; i++)
  {
    uint8_t pin;
    if (i <= 10)
    {
      pin = i;
    }
    else
    {
      pin = i + 2;
    }

    if (pwm[i] > stepCounter)
    {
      digitalWrite(pin, HIGH);
    }
    else
    {
      digitalWrite(pin, LOW);
    }

  }
  stepCounter++;
  if (stepCounter > 255)
  {
    stepCounter = 0;
  }
}
