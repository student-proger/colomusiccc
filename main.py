'''
* Author:       Gladyshev Dmitriy (2021)
*
* Design Name:  ColormusicCC
* Description:  Программа для управления цветомузыкой
'''
"""
TODO
Стробоскоп
Секвенсор на ланчпаде.
Управление чувствительностью с ланчпада
Вынести отправку данных в отдельный поток
Переделать на multiprocessing
Разбить проект на модули
Отключение ламп при выходе из программы
Режим освещения

"""

__version__ = "0.0.1a"

import os
import sys
import time
import json
import math
import socket

import numpy as np
import sounddevice as sounddev
from pywinusb import hid

from threading import Thread, Lock

from os import environ
environ['PYGAME_HIDE_SUPPORT_PROMPT'] = '1'

import pygame
import pygame.midi
from pygame.locals import *

# Qt
from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.QtWidgets import QTableWidgetItem, QLabel, QInputDialog, QComboBox, QSystemTrayIcon
from PyQt5.QtWidgets import QMessageBox, QWidget, QMenu
from PyQt5.QtGui import QPixmap, QPainter, QColor, QBrush, QFont
from PyQt5.QtCore import Qt, QRect
# design
import mainform

settings = {
    "udp": {
        "ip": "192.168.10.100",         # IP адрес цветомузыки
        "port": 8888                    # порт цветомузыки
    },
    "mode": 1,                          # Активный режим работы
    "sensitivityRYG": [100, 100, 100],  # чувствительность по каналам
    "midi": {
        "dev_name": "X-TOUCH MINI"      # Название MIDI устройства
    }
}

# Индексы элементов списка leds. Соответственно цветам светодиодов.
RED = 0
GREEN = 1
BLUE = 2

# Цвета для вывода на Launchpad. Для мигающего необходимо прибавить LPC_FLASH к основному значению.
LPC_OFF = 12
LPC_RED = (0, 0x0D, 0x0E, 0x0F)
LPC_GREEN = (0, 0x1C, 0x2C, 0x3C)
LPC_ORANGE = (0, 0x1D, 0x2E, 0x3F)
LPC_YELLOW = 0x3E
LPC_FLASH = -4

MIDI_CC = 176
MIDI_PROGRAM = 192
MIDI_LED_BUTTON = 154
MIDI_KNOB = 186

# Кнопки без фиксации
buttPress = {
    "agbvPlus": [150, 35, 20, 20, "+", False, None],
    "agbvMinus": [80, 35, 20, 20, "-", False, None]
}

soundDevice = None
block_duration = 20
low = 40
high = 2000
gain = 7

stop_thread = False
lock_stop_thread = Lock()

spectrum = []
lock_spectrum = Lock()
leftLevel = 0
rightLevel = 0

# Путь к папке с настройками
datapath = ""

def messageBox(title, s):
    """ Отображение диалогового окна с сообщением

    title -- заголовок окна
    s -- сообщение
    """
    msg = QMessageBox()
    msg.setIcon(QMessageBox.Information)
    msg.setText(s)
    msg.setWindowTitle(title)
    msg.exec_()


def saveSettings():
    """ Сохранение настроек в файл """
    try:
        with open(datapath + 'settings.json', 'w') as f:
            json.dump(settings, f)
    except:
        messageBox("Критическая ошибка", "Ошибка сохранения файла настроек. Возможно нет прав доступа на запись.")


def loadSettings():
    """ Загрузка настроек из файла """
    global settings
    try:
        with open(datapath + 'settings.json') as f:
            settings = json.load(f)
    except FileNotFoundError:
        pass
    except:
        messageBox("Критическая ошибка", "Ошибка чтения файла настроек. Возможно нет прав доступа на чтение.")


def isWindows():
    """ Проверяет, под какой ОС запущено приложение. 

    Возвращает True, если Windows.
    """
    if os.name == "nt":
        return True
    else:
        return False


class MidiDevice:
    """ Класс для работы с MIDI устройствами """
    def __init__(self):
        pygame.init()
        pygame.fastevent.init()
        pygame.midi.init()
        self.DoubleBufferActivePage = 0
        self.__print_device_info()

    def __del__(self):
        """ Деструктор класса MidiDevice.

        Закрываем ресурсы и ждём завершения дочерних потоков.
        """
        try:
            self.devOut.close()
        except AttributeError:
            pass
        self.midi_thread.join()
        pygame.midi.quit()
    
    def startInput(self, device_id = None, callback = None):
        """ Включение MIDI-устройства ввода

        device_id -- ID MIDI-устройства
        callback(msg) -- callback функция, вызываемая при получении данных от устройства """
        self.midi_thread = self.MidiInputThread(device_id, callback)
        self.midi_thread.start()


    def startOutput(self, device_id = None):
        """ Включение MIDI-устройства вывода

        device_id -- ID MIDI-устройства
        """
        if device_id is None:
            port = pygame.midi.get_default_output_id()
        else:
            port = device_id

        if port != -1:
            print("\nusing output_id :%s:" % port)
            try:
                self.devOut = pygame.midi.Output(port, 0)
            except:
                self.devOut = None

    def send(self, msg, key, velocity):
        """ Отправка данных на устройство """
        try:
            self.devOut.write_short(msg, key, velocity)
        except AttributeError:
            pass

    def resetLaunchpad(self):
        """ Launchpad: Сброс ланчпада """
        self.send(0xB0, 0, 0)
    
    def setLed(self, x, y, c = None):
        """ Launchpad: Включает выбранный светодиод.
        Варианты вызова:
        setLed(x, y, color), где x,y - координаты кнопки по сетке
        setLed(n, color), где n - номер кнопки по-порядку
        """
        if c == None:
            n = x
            color = y
        else:
            n = 16 * y + x
            color = c
        self.send(0x90, n, color)

    def setTopLed(self, n, color):
        """ Launchpad: Включение светодиода на ланчпаде в верхем ряду кнопок

        :param n: номер кнопки
        :param color: цвет
        """
        self.send(0xB0, 0x68 + n, color)


    def doubleBufferEnable(self):
        """ Launchpad: Включение двойной буферизации """
        self.send(0xB0, 0x00, 0x31)
        self.DoubleBufferActivePage = 0


    def doubleBufferDisable(self):
        """ Launchpad: Выключение двойной буферизации """
        self.send(0xB0, 0x00, 0x30)

    def swapBuffer(self):
        """ Launchpad: Обмен страниц буфера """
        if self.DoubleBufferActivePage == 0:
            self.send(0xB0, 0x00, 0x34)
        else:
            self.send(0xB0, 0x00, 0x31)

    def flashEnable(self):
        """ Launchpad: Включение режима мигания """
        self.send(0xB0, 0x00, 0x28)

    def flashActive(self, enable):
        """ Launchpad: активация мигания """
        if enable:
            self.send(0xB0, 0x00, 0x20)
        else:
            self.send(0xB0, 0x00, 0x21)

    def rapidLedUpdate(self, velocity1, velocity2):
        """ Launchpad: Быстрое обновление данных. В качестве параметров передаются сразу два цвета для двух кнопок"""
        self.send(0x92, velocity1, velocity2)

    def allLedsOn(self, brightness):
        """ Launchpad: Включение всех светодиодов.

        :param brightness: яркость (1-3)
        """
        if (brightness >= 1) and (brightness <= 3):
            self.send(0xB0, 0x00, 0x7C + brightness)

    def demo(self):
        """ Launchpad: демка """
        for x in range(0, 4):
            for y in range(0, 4):
                self.setLed(x, y, LPC_GREEN[3])
        time.sleep(0.1)
        for x in range(0, 4):
            for y in range(0, 4):
                self.setLed(x, y, LPC_OFF)

        for x in range(4, 8):
            for y in range(4, 8):
                self.setLed(x, y, LPC_GREEN[3])
        time.sleep(0.1)
        for x in range(4, 8):
            for y in range(4, 8):
                self.setLed(x, y, LPC_OFF)

        for x in range(0, 4):
            for y in range(4, 8):
                self.setLed(x, y, LPC_RED[3])
        time.sleep(0.1)
        for x in range(0, 4):
            for y in range(4, 8):
                self.setLed(x, y, LPC_OFF)

        for x in range(4, 8):
            for y in range(0, 4):
                self.setLed(x, y, LPC_RED[3])
        time.sleep(0.1)
        for x in range(4, 8):
            for y in range(0, 4):
                self.setLed(x, y, LPC_OFF)

        for x in range(2, 6):
            for y in range(2, 6):
                self.setLed(x, y, LPC_ORANGE[3])
        time.sleep(0.1)
        for x in range(2, 6):
            for y in range(2, 6):
                self.setLed(x, y, LPC_OFF)

    def __print_device_info(self):
        """ Вывод информации о подключенных MIDI устройствах """
        for i in range( pygame.midi.get_count() ):
            r = pygame.midi.get_device_info(i)
            (interf, name, input, output, opened) = r

            in_out = ""
            if input:
                in_out = "(input)"
            if output:
                in_out = "(output)"

            print ("%2i: interface: %s, name: %s, opened: %s  %s" %
                   (i, interf.decode('utf-8'), name.decode('utf-8'), opened, in_out))

    def findDevice(self, devname):
        """ Ищет MIDI устройство по его имени.

        Возвращает кортеж из ID устройства ввода и ID устройства вывода.
        None вместо значения, если устройство с требуемым именем не найдено.
        """
        id_in = None
        id_out = None

        for i in range( pygame.midi.get_count() ):
            r = pygame.midi.get_device_info(i)
            (interf, name, input, output, opened) = r

            if name.decode('utf-8') == devname:
                if input:
                    id_in = i
                if output:
                    id_out = i

        return (id_in, id_out)


    class MidiInputThread(Thread):
        """ Поток работы с MIDI устройством """
        def __init__(self, device_id, callback):
            Thread.__init__(self)
            self.device_id = device_id
            self.callback = callback

        def run(self):
            print("Start MIDI thread")
            if self.device_id != -1:
                self.input_main(self.device_id, self.callback)
            print("Stop MIDI thread")
        
        def input_main(self, device_id = None, callback = None):
            event_get = pygame.fastevent.get
            event_post = pygame.fastevent.post

            if device_id is None:
                input_id = pygame.midi.get_default_input_id()
            else:
                input_id = device_id

            if input_id != -1:
                print ("using input_id :%s:" % input_id)
                devIn = pygame.midi.Input( input_id )

                while True:
                    time.sleep(0.05)
                    events = event_get()
                    for e in events:
                        if e.type in [pygame.midi.MIDIIN]:
                            print (e)

                    if devIn.poll():
                        midi_events = devIn.read(10)
                        for item in midi_events:
                            midi_msg = item[0]
                            callback(midi_msg)

                        # convert them into pygame events.
                        #midi_evs = pygame.midi.midis2events(midi_events, devIn.device_id)
                        #for m_e in midi_evs:
                        #    event_post( m_e )

                    lock_stop_thread.acquire()
                    if stop_thread:
                        lock_stop_thread.release()
                        break
                    lock_stop_thread.release()

                devIn.close()
            else:
                print("MIDI device not found.")
        

class SoundThread(Thread):
    """ Класс захвата аудиопотока. Выполняется в отдельном потоке.
    Здесь же происходит быстрое преобразование Фурье.
    """
    def __init__(self):
        Thread.__init__(self)
    
    def run(self):
        print("Start Sound capture thread")
        global gain
        try:
            samplerate = sounddev.query_devices(soundDevice, 'input')['default_samplerate']

            delta_f = (high - low) / (60 - 1)
            fftsize = math.ceil(samplerate / delta_f)
            low_bin = math.floor(low / delta_f)

            # callback-функция, которая вызывается при получении звукового сэмпла
            def callback(indata, frames, time, status):
                global spectrum
                global leftLevel
                global rightLevel

                if status:
                    text = '************************ ' + str(status) + ' ************************'
                    print(text)
                
                # Быстрые преобразования Фурье
                # Левый канал
                magnitude = np.abs(np.fft.rfft(indata[:, 0], n=fftsize))
                magnitude *= gain / fftsize
                leftspectrum = []
                for x in magnitude[low_bin:low_bin + 60]:
                    leftspectrum.append(round(x * 100000))
                # Правый канал
                magnitude = np.abs(np.fft.rfft(indata[:, 1], n=fftsize))
                magnitude *= gain / fftsize
                rightspectrum = []
                for x in magnitude[low_bin:low_bin + 60]:
                    rightspectrum.append(round(x * 100000))

                lock_spectrum.acquire()
                leftLevel = max(leftspectrum)
                rightLevel = max(rightspectrum)
                spectrum = []
                for i in range(0, len(leftspectrum)):
                    spectrum.append(max(leftspectrum[i], rightspectrum[i]))
                lock_spectrum.release()

            # Захват звука с аудиоустройства
            with sounddev.InputStream(device=soundDevice, channels=2, callback=callback,
                                blocksize=int(samplerate * block_duration / 1000),
                                samplerate=samplerate):
                while True:
                    time.sleep(1)
                    lock_stop_thread.acquire()
                    if stop_thread:
                        lock_stop_thread.release()
                        break
                    lock_stop_thread.release()
            print("Stop Sound capture thread")

        except KeyboardInterrupt:
            print('Interrupted by user')
        except Exception as e:
            print(type(e).__name__ + ': ' + str(e))


class SystemTrayIcon(QSystemTrayIcon):
    """ Класс значка в системном трее """
    def __init__(self, icon, parent=None):
        QSystemTrayIcon.__init__(self, icon, parent)
        menu = QMenu(parent)
        exitAction = menu.addAction("Exit")
        self.setContextMenu(menu)


class ColormusicApp(QtWidgets.QMainWindow, mainform.Ui_MainWindow):
    """ Класс главного окна приложения """
    def __init__(self):
        super().__init__()
        self.setupUi(self)  # Это нужно для инициализации нашего дизайна

        # Кнопки с фиксацией
        #   X, Y, W, H, текст кнопки, состояние, callback
        self.butt = {
            "OnOff": [10, 10, 50, 20, "ON", False, None],
            "AutoGain": [80, 10, 90, 20, "Auto gain", False, None],
            "LogComp": [180, 10, 90, 20, "Comp", False, None],
            "Strob1": [280, 10, 45, 45, "Strob", False, self.eventStrobButton],
            "Strob2": [330, 10, 45, 45, "Strob", False, self.eventStrobButton],
            "Strob3": [380, 10, 45, 45, "Strob", False, self.eventStrobButton],
            "Strob4": [430, 10, 45, 45, "Strob", False, self.eventStrobButton],
            "Strob5": [480, 10, 45, 45, "Strob", False, self.eventStrobButton]
        }

        # Установка значений элементам управления из текущих настроек
        self.sensR.setValue(settings["sensitivityRYG"][0])
        self.sensY.setValue(settings["sensitivityRYG"][1])
        self.sensG.setValue(settings["sensitivityRYG"][2])

        # Номер активной страницы ланчпада
        self.LaunchPadPage = 1

        # Активность стробоскопов
        self.StroboActive = False
        self.StroboTimer = QtCore.QTimer()
        self.StroboTimer.timeout.connect(self.strob)

        # Список состояний светодиодов. 10 штук по три (RGB)
        self.leds = []
        for i in range(0, 10):
            self.leds.append([0, 0, 0])

        # Список для хранения частотного спектра сигнала
        self.spectrum = [0] * 60

        # Для автоматического уровня сигнала
        self.maxvalue = 1
        self.lastMaxPeakTime = time.time()
        self.agBurstValue = 0

        self.sensR.valueChanged.connect(lambda: self.sensitivityChange(0))
        self.sensY.valueChanged.connect(lambda: self.sensitivityChange(1))
        self.sensG.valueChanged.connect(lambda: self.sensitivityChange(2))

        # Данные для 4-х канальной цветомузыки
        # Red, yellow, green, blue
        self.chanRYGB = [False, False, False, False]
        # Таймеры выключения ламп RGBY (R,Y,G)
        self.lamptimer = [QtCore.QTimer(), QtCore.QTimer(), QtCore.QTimer()]
        self.lamptimer[0].timeout.connect(lambda: self.stoplamp(0))
        self.lamptimer[1].timeout.connect(lambda: self.stoplamp(1))
        self.lamptimer[2].timeout.connect(lambda: self.stoplamp(2))

        # Главный таймер
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.on_timer)
        self.timer.start(20)

        self.openHID(vid = 0x1EAF, pid = 0x0028)

        self.midi = MidiDevice()
        midi_id = self.midi.findDevice(settings["midi"]["dev_name"])
        self.midi.startInput(device_id = midi_id[0], callback = self.midiCallback)
        self.midi.startOutput(midi_id[1])

        self.setMidiState()

        #self.midi.resetLaunchpad()
        #self.midi.demo()
        #self.midi.setLed(8, 0, LPC_YELLOW)
        #self.midi.setLed(8, 1, LPC_RED[1])
        #self.midi.setLed(8, 2, LPC_RED[1])


    def sensitivityChange(self, id):
        """ Event на изменение положения ручек регулировки чувствительности """
        global settings
        if id == 0:
            value = self.sensR.value()
        elif id == 1:
            value = self.sensY.value()
        else:
            value = self.sensG.value()
        # value = (100 - value) * 10
        settings["sensitivityRYG"][id] = value


    def closeRes(self):
        """ Закрытие всех ресурсов, которые были выделены во время работы.

        Эту функцию надо вызывать в конце работы приложения, перед уничтожением формы.
        """
        self.midi.resetLaunchpad()
        del self.midi


    def setMidiState(self):
        """ Функция для установки начального состояния MIDI устройства """
        if settings["midi"]["dev_name"] == "X-TOUCH MINI":
            # Вид индикации энкодеров
            self.midi.send(MIDI_CC, 1, 2)
            self.midi.send(MIDI_CC, 2, 2)
            self.midi.send(MIDI_CC, 3, 2)
            # Текущие положения энкодеров
            self.midi.send(186, 1, settings["sensitivityRYG"][0])
            self.midi.send(186, 2, settings["sensitivityRYG"][1])
            self.midi.send(186, 3, settings["sensitivityRYG"][2])


    def midiCallback(self, message):
        """ callback функция, которая вызывается при получении сообщения от MIDI устройства.

        message -- MIDI сообщение. """
        print("MIDI: ", message)

        msg = message[0]
        key = message[1]
        velocity = message[2]
        
        if settings["midi"]["dev_name"] == "X-TOUCH MINI":
            if msg == MIDI_KNOB: # Информация о вращении ручек энкодеров
                if key == 1:
                    self.sensR.setValue(velocity)
                if key == 2:
                    self.sensY.setValue(velocity)
                if key == 3:
                    self.sensG.setValue(velocity)

        #self.midi.send(186, message[1], 50) состояние ручек
        #self.midi.send(176, 2, 2) вид светодиодов


    def stoplamp(self, index):
        """ Выключение лампы с индексом index """
        self.chanRYGB[index] = False
        self.lamptimer[index].stop()


    def strob(self):
        """ Генерация строба на цветомузыке """
        buf = [0x00]
        for i in range(0, 30):
            buf.append(0xFF)
        try:
            self.out_report.set_raw_data(buf)
            self.out_report.send()
        except AttributeError:
            return


    def eventStrobButton(self, name, state):
        """ Событие нажатия на кнопку стробоскопа """
        for i in range(1, 6):
            s = "Strob" + str(i)
            self.butt[s][5] = False
        if state:
            self.butt[name][5] = True

        if state:
            if name == "Strob1":
                bpm = 60
            elif name == "Strob2":
                bpm = 120
            elif name == "Strob3":
                bpm = 300
            elif name == "Strob4":
                bpm = 600
            elif name == "Strob5":
                bpm = 1200

            period = round(60000 / bpm)
            self.StroboActive = True
            self.StroboTimer.start(period)
        else:
            self.StroboTimer.stop()


    def writeHID(self):
        """ Отправка данных на USB HID устройство """
        buf = [0x00]

        for item in self.leds:
            for k in item:
                buf.append(k)

        try:
            self.out_report.set_raw_data(buf)
            self.out_report.send()
        except AttributeError:
            return
        except:
            return


    def openHID(self, vid, pid):
        """ Открытие USB HID устройства для работы.

        vid -- Vendor ID
        pid -- Product ID
        """
        filter = hid.HidDeviceFilter(vendor_id = vid, product_id = pid)
        devices = filter.get_devices()
        if devices:
            self.device = devices[0]
            print("USB device founded.")
            self.device.open()
            
            self.out_report = self.device.find_output_reports()[0]


    def closeHID(self):
        """ Закрытие USB HID устройства """
        buf = [0x00] * 31
        try:
            self.out_report.set_raw_data(buf)
            self.out_report.send()
            self.device.close()
        except AttributeError:
            return
        except:
            pass

    
    def sendUDP(self):
        """ Отправка данных на сетевое устройство """
        c = []
        # Дежурный канал
        if (self.chanRYGB[0] == False) and (self.chanRYGB[1] == False) and (self.chanRYGB[2] == False):
            self.chanRYGB[3] = True
        else:
            self.chanRYGB[3] = False

        for item in self.chanRYGB:
            if item == True:
                c.append('1')
            else:
                c.append('0')
        sc = "".join(c)

        dev_ip = settings["udp"]["ip"]
        dev_port = settings["udp"]["port"]

        byte_message = bytes(sc, "utf-8")
        opened_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        opened_socket.sendto(byte_message, (dev_ip, dev_port))

    
    def mousePressEvent(self, QMouseEvent):
        """ Событие нажатия кнопки мыши """
        xx = QMouseEvent.x()
        yy = QMouseEvent.y()
        for item in self.butt:
            x, y = self.butt[item][0], self.butt[item][1]
            w, h = self.butt[item][2], self.butt[item][3]
            if (xx >= x) and (xx < x + w) and (yy >= y) and (yy < y + h):
                self.butt[item][5] = not self.butt[item][5]
                proc = self.butt[item][6]
                if proc:
                    proc(item, self.butt[item][5])

        for item in buttPress:
            x, y = buttPress[item][0], buttPress[item][1]
            w, h = buttPress[item][2], buttPress[item][3]
            if (xx >= x) and (xx < x + w) and (yy >= y) and (yy < y + h):
                buttPress[item][5] = True
                if item == "agbvPlus":
                    self.agBurstValue += 5
                    if self.agBurstValue > 70:
                        self.agBurstValue = 70
                elif item == "agbvMinus":
                    self.agBurstValue -= 5
                    if self.agBurstValue < 0:
                        self.agBurstValue = 0

    
    def mouseReleaseEvent(self, QMouseEvent):
        """ Событие отпускания кнопки мыши """
        xx = QMouseEvent.x()
        yy = QMouseEvent.y()
        for item in buttPress:
            if buttPress[item][5]:
                buttPress[item][5] = False


    def on_timer(self):
        """ Обработчик события главного таймера.
        Таймер вызывается каждые 20 мс. Здесь происходит обработка данных спектра,
        выполнение алгоритма переключения светодиодов и отрисовка GUI.
        """
        global spectrum

        lock_spectrum.acquire()
        self.spectrum = []
        for x in spectrum:
            self.spectrum.append(x)
        lock_spectrum.release()

        if len(self.spectrum) != 60:
            self.spectrum = [0] * 60

        self.update()

        # Auto gain
        if self.butt["AutoGain"][5]:
            # Если максимальный уровень сигнала не превышает 20, то считаем, что тишина
            if max(self.spectrum[0:30]) > 20:
                if time.time() - self.lastMaxPeakTime > 15:
                    self.maxvalue = 1

                maxs = max(self.spectrum)
                if maxs > self.maxvalue:
                    self.maxvalue = maxs
                    self.lastMaxPeakTime = time.time()
                gainCorrection = ((self.agBurstValue / 100) * 1000 + 1000) / self.maxvalue
                for i in range(0, 60):
                    self.spectrum[i] = self.spectrum[i] * gainCorrection
            else:
                self.maxvalue = 1
        # ==========================


        # Логарифмический компрессор
        if self.butt["LogComp"][5]:
            for i in range(0, 60):
                try:
                    # Немного математической магии :)
                    self.spectrum[i] = ((self.agBurstValue / 100) * 1000 + 1000) * (1 / math.log10(1000 / 50)) * math.log10(self.spectrum[i] / 50)
                    if self.spectrum[i] < 0:
                        self.spectrum[i] = 0
                except ValueError:
                    self.spectrum[i] = 0
        # ==========================

        # Обработка данных для 10 канальной RGB цветомузыки
        if settings["mode"] == 1:
            self.processMode1()
        elif settings["mode"] == 2:
            self.processMode2()
        elif settings["mode"] == 3:
            self.processMode3()
        elif settings["mode"] == 4:
            self.processMode4()
        elif settings["mode"] == 5:
            self.processMode5()
        elif settings["mode"] == 6:
            self.processMode6()
        elif settings["mode"] == 7:
            self.processMode7()

        # Обработка данных для 4 канальной RGBY цветомузыки
        self.processRGBY()
     
        self.writeHID()
        self.sendUDP()


    def paintEvent(self, e):
        """ Обработчик перерисовки формы """
        qp = QPainter()
        qp.begin(self)
        self.drawUI(qp)
        qp.end()


    def drawSimpleRect(self, qp, x1, y1, x2, y2):
        """ Рисует пустой прямоугольник """
        qp.drawLine(x1, y1, x2, y1)
        qp.drawLine(x2, y1, x2, y2)
        qp.drawLine(x2, y2, x1, y2)
        qp.drawLine(x1, y2, x1, y1)


    def drawUI(self, qp):
        """ Рисуем GUI """
        activeColor = QColor(234, 237, 242)
        bgColor = QColor(39, 72, 135)

        # Фон
        qp.setPen(bgColor)
        qp.setBrush(bgColor)
        qp.drawRect(0, 0, 700, 500)

        # Рамки
        qp.setPen(activeColor)
        self.drawSimpleRect(qp, 48, 60, 652, 164)
        self.drawSimpleRect(qp, 11, 60, 35, 164)

        # Спектр сигнала
        qp.setPen(bgColor)
        if len(self.spectrum) != 0:
            maxv = 1000 #max(self.spectrum)

            if maxv < 1000:
                maxv = 1000

            x = 0
            for v in self.spectrum:
                for y in range(0, 10):

                    if v >= (maxv/10)*(y+1):
                        if y >= 8:
                            qp.setBrush(QColor(255, 0, 0))
                        elif y >= 6:
                            qp.setBrush(QColor(255, 255, 0))
                        else:
                            qp.setBrush(QColor(0, 255, 0))
                    else:
                        qp.setBrush(bgColor)
                    qp.drawRect(50 + 10*x, 62 + 10*(9 - y), 9, 9)
                x += 1

            for y in range(0, 10):
                if leftLevel >= (maxv/10)*(y+1):
                    if y >= 8:
                        qp.setBrush(QColor(255, 0, 0))
                    elif y >= 6:
                        qp.setBrush(QColor(255, 255, 0))
                    else:
                        qp.setBrush(QColor(0, 255, 0))
                else:
                    qp.setBrush(bgColor)
                qp.drawRect(13, 62 + 10*(9 - y), 9, 9)

                if rightLevel >= (maxv/10)*(y+1):
                    if y >= 8:
                        qp.setBrush(QColor(255, 0, 0))
                    elif y >= 6:
                        qp.setBrush(QColor(255, 255, 0))
                    else:
                        qp.setBrush(QColor(0, 255, 0))
                else:
                    qp.setBrush(bgColor)
                qp.drawRect(23, 62 + 10*(9 - y), 9, 9)

        # Рисуем кнопки
        for item in self.butt:
            x, y = self.butt[item][0], self.butt[item][1]
            w, h = self.butt[item][2], self.butt[item][3]
            if self.butt[item][5]:
                qp.setBrush(activeColor)
            else:
                qp.setBrush(bgColor)
            qp.setPen(activeColor)
            qp.drawRect(x, y, w, h)

            if self.butt[item][5]:
                qp.setPen(bgColor)
            else:
                qp.setPen(activeColor)
            qp.setFont(QFont('Arial', 10))
            qp.drawText(QRect(x, y, w, h), Qt.AlignCenter, self.butt[item][4])

        for item in buttPress:
            x, y = buttPress[item][0], buttPress[item][1]
            w, h = buttPress[item][2], buttPress[item][3]
            if buttPress[item][5]:
                qp.setBrush(activeColor)
            else:
                qp.setBrush(bgColor)
            qp.setPen(activeColor)
            qp.drawRect(x, y, w, h)

            if buttPress[item][5]:
                qp.setPen(bgColor)
            else:
                qp.setPen(activeColor)
            qp.setFont(QFont('Arial', 10))
            qp.drawText(QRect(x, y, w, h), Qt.AlignCenter, buttPress[item][4])

        # Текущее состояние светодиодов
        qp.setPen(activeColor)
        for i in range(0, 10):
            qp.setBrush(QColor(self.leds[i][RED], self.leds[i][GREEN], self.leds[i][BLUE]))
            qp.drawRect(30 + i * 22, 200, 20, 20)

        # Текущее состояние светодиодов RGBY
        qp.setPen(activeColor)
        for i in range(0, 4):
            if self.chanRYGB[i]:
                if i == 0:
                    qp.setBrush(QColor(255, 0, 0))
                elif i == 1:
                    qp.setBrush(QColor(255, 255, 0))
                elif i == 2:
                    qp.setBrush(QColor(0, 255, 0))
                else:
                    qp.setBrush(QColor(0, 0, 255))
            else:
                qp.setBrush(QColor(0, 0, 0))
            qp.drawRect(280 + i * 22, 200, 20, 20)

        # Надписи
        qp.setPen(activeColor)
        qp.setFont(QFont('Arial', 10))
        qp.drawText(QRect(100, 35, 50, 20), Qt.AlignCenter, str(self.agBurstValue) + "%")
        qp.drawText(QRect(self.sensR.x(), self.sensR.y() - 10, self.sensR.width(), 10), Qt.AlignCenter, str(settings["sensitivityRYG"][0]))
        qp.drawText(QRect(self.sensY.x(), self.sensY.y() - 10, self.sensY.width(), 10), Qt.AlignCenter, str(settings["sensitivityRYG"][1]))
        qp.drawText(QRect(self.sensG.x(), self.sensG.y() - 10, self.sensG.width(), 10), Qt.AlignCenter, str(settings["sensitivityRYG"][2]))


    def processRGBY(self):
        """ Обработка спектра для вывода на цветомузыку. """
        if len(self.spectrum) == 0:
            return
        ch = [0, 0, 0]
        ch[0] = max(self.spectrum[0:4])
        ch[1] = max(self.spectrum[4:8])
        ch[2] = max(self.spectrum[8:13])

        #ch[0] = max(self.spectrum[0:2])
        #ch[1] = max(self.spectrum[2:4])
        #ch[2] = max(self.spectrum[4:8])
        #ch[3] = max(self.spectrum[8:14])
        #ch[4] = max(self.spectrum[14:30])

        # Если превышен порог, то выставляем флаг включения лампы и запускаем таймер, который её затем выключит
        for i in range(0, 3):
            value = (128 - settings["sensitivityRYG"][i]) * 7.8125
            if ch[i] > value:
                self.chanRYGB[i] = True
                self.lamptimer[i].start(100)
            else:
                pass
                #self.chanRYGB[i] = False


    def processMode1(self):
        if len(self.spectrum) == 0:
            return
        ch = [0, 0, 0, 0, 0]
        ch[0] = max(self.spectrum[0:2])
        ch[1] = max(self.spectrum[2:4])
        ch[2] = max(self.spectrum[4:8])
        ch[3] = max(self.spectrum[8:14])
        ch[4] = max(self.spectrum[14:30])

        # Затухание светодиодов
        for i in range(0, 5):
            self.leds[i][RED] -= 50
            self.leds[i][GREEN] -= 50
            self.leds[i][BLUE] -= 50
            if self.leds[i][RED] < 0:
                self.leds[i][RED] = 0
            if self.leds[i][GREEN] < 0:
                self.leds[i][GREEN] = 0
            if self.leds[i][BLUE] < 0:
                self.leds[i][BLUE] = 0

        for i in range(0, 5):
            if ch[i] > 900:
                self.leds[i][RED] = 255
            elif ch[i] > 800:
                self.leds[i][GREEN] = 255
            elif ch[i] > 650:
                self.leds[i][BLUE] = 255

        for i in range(0, 5):
            self.leds[9 - i][RED] = self.leds[i][RED]
            self.leds[9 - i][GREEN] = self.leds[i][GREEN]
            self.leds[9 - i][BLUE] = self.leds[i][BLUE]
        

    def processMode2(self):
        if len(self.spectrum) == 0:
            return
        ch = [0, 0, 0, 0]
        ch[0] = max(self.spectrum[0:5])
        ch[1] = max(self.spectrum[5:23])
        ch[2] = max(self.spectrum[23:60])

        for i in range(0, 10):
            self.leds[i][RED] -= 50
            self.leds[i][GREEN] -= 50
            self.leds[i][BLUE] -= 50
            if self.leds[i][RED] < 0:
                self.leds[i][RED] = 0
            if self.leds[i][GREEN] < 0:
                self.leds[i][GREEN] = 0
            if self.leds[i][BLUE] < 0:
                self.leds[i][BLUE] = 0

        if ch[0] > 750:
            self.leds[0][RED] = 255
            self.leds[1][RED] = 255
            self.leds[2][RED] = 255
            self.leds[3][RED] = 255
        if ch[1] > 750:
            self.leds[3][GREEN] = 255
            self.leds[4][GREEN] = 255
            self.leds[5][GREEN] = 255
            self.leds[6][GREEN] = 255
        if ch[2] > 750:
            self.leds[6][BLUE] = 255
            self.leds[7][BLUE] = 255
            self.leds[8][BLUE] = 255
            self.leds[9][BLUE] = 255


    def processMode3(self):
        if len(self.spectrum) == 0:
            return
        ch = [0, 0, 0, 0]
        ch[0] = max(self.spectrum[0:5])
        ch[1] = max(self.spectrum[5:23])
        ch[2] = max(self.spectrum[23:60])

        for i in range(0, 10):
            self.leds[i][RED] -= 50
            self.leds[i][GREEN] -= 50
            self.leds[i][BLUE] -= 50
            if self.leds[i][RED] < 0:
                self.leds[i][RED] = 0
            if self.leds[i][GREEN] < 0:
                self.leds[i][GREEN] = 0
            if self.leds[i][BLUE] < 0:
                self.leds[i][BLUE] = 0

        if ch[0] > 750:
            self.leds[0][RED] = 255
            self.leds[3][RED] = 255
            self.leds[6][RED] = 255
            self.leds[9][RED] = 255
        if ch[1] > 750:
            self.leds[1][GREEN] = 255
            self.leds[4][GREEN] = 255
            self.leds[5][GREEN] = 255
            self.leds[8][GREEN] = 255
        if ch[2] > 750:
            self.leds[2][BLUE] = 255
            self.leds[4][BLUE] = 255
            self.leds[5][BLUE] = 255
            self.leds[7][BLUE] = 255


    def processMode4(self):
        if len(self.spectrum) == 0:
            return
        ch = [0, 0, 0, 0]
        ch[0] = max(self.spectrum[0:5])
        ch[1] = max(self.spectrum[5:23])
        ch[2] = max(self.spectrum[23:60])

        for i in range(0, 10):
            self.leds[i][RED] -= 50
            self.leds[i][GREEN] -= 50
            self.leds[i][BLUE] -= 50
            if self.leds[i][RED] < 0:
                self.leds[i][RED] = 0
            if self.leds[i][GREEN] < 0:
                self.leds[i][GREEN] = 0
            if self.leds[i][BLUE] < 0:
                self.leds[i][BLUE] = 0

        if ch[0] > 750:
            for i in range(0, 10):
                self.leds[i][RED] = 255
        if ch[1] > 750:
            for i in range(0, 10):
                self.leds[i][GREEN] = 255
        if ch[2] > 750:
            for i in range(0, 10):
                self.leds[i][BLUE] = 255


    def processMode5(self):
        if len(self.spectrum) == 0:
            return
        ch = [0, 0, 0]
        ch[0] = max(self.spectrum[0:5])
        ch[1] = max(self.spectrum[5:23])
        ch[2] = max(self.spectrum[23:60])

        for i in range(0, 4):
            self.leds[i][RED] = self.leds[i + 1][RED]
            self.leds[i][GREEN] = self.leds[i + 1][GREEN]
            self.leds[i][BLUE] = self.leds[i + 1][BLUE]

        for i in range(4, 6):
            self.leds[i][RED] -= 50
            self.leds[i][GREEN] -= 50
            self.leds[i][BLUE] -= 50
            if self.leds[i][RED] < 0:
                self.leds[i][RED] = 0
            if self.leds[i][GREEN] < 0:
                self.leds[i][GREEN] = 0
            if self.leds[i][BLUE] < 0:
                self.leds[i][BLUE] = 0

        if ch[0] > 750:
            self.leds[4][RED] = 255
        if ch[1] > 750:
            self.leds[4][GREEN] = 255
        if ch[2] > 750:
            self.leds[4][BLUE] = 255

        for i in range(0, 5):
            self.leds[9 - i][RED] = self.leds[i][RED]
            self.leds[9 - i][GREEN] = self.leds[i][GREEN]
            self.leds[9 - i][BLUE] = self.leds[i][BLUE]


    def processMode6(self):
        if len(self.spectrum) == 0:
            return
        ch = [0] * 10
        for i in range(0, 10):
            ch[i] = max(self.spectrum[i * 3:i * 3 + 3])


        for i in range(0, 10):
            self.leds[i][RED] = 0
            self.leds[i][GREEN] = 0
            self.leds[i][BLUE] = 0
            v = round(ch[i] / 3)
            if v > 255:
                v = 255
            if ch[i] > 800:
                self.leds[i][RED] = v
            elif ch[i] > 600:
                self.leds[i][BLUE] = v
            else:
                self.leds[i][GREEN] = v


        

        #for i in range(0, 5):
            #self.leds[9 - i][RED] = self.leds[i][RED]
            #self.leds[9 - i][GREEN] = self.leds[i][GREEN]
            #self.leds[9 - i][BLUE] = self.leds[i][BLUE]


    def processMode7(self):
        if len(self.spectrum) == 0:
            return
        ch = [0, 0, 0, 0]
        ch[0] = max(self.spectrum[0:5])
        ch[1] = max(self.spectrum[5:23])
        ch[2] = max(self.spectrum[23:60])

        for i in range(0, 3):
            ch[i] = ch[i]**4 / 1000000000

        for i in range(0, 3):
            ch[i] = round(ch[i] / 3)
            if ch[i] > 255:
                ch[i] = 255

        self.leds[0][RED] = ch[0]
        self.leds[1][RED] = ch[0]
        self.leds[2][RED] = ch[0]
        self.leds[3][RED] = ch[0]

        self.leds[3][GREEN] = ch[1]
        self.leds[4][GREEN] = ch[1]
        self.leds[5][GREEN] = ch[1]
        self.leds[6][GREEN] = ch[1]

        self.leds[6][BLUE] = ch[2]
        self.leds[7][BLUE] = ch[2]
        self.leds[8][BLUE] = ch[2]
        self.leds[9][BLUE] = ch[2]


def main():
    global stop_thread
    global midi
    global datapath

    if isWindows():
        datapath = os.getenv('APPDATA') + "\\ColormusicCC\\"
        if not os.path.exists(datapath):
            os.mkdir(datapath)

    loadSettings()

    app = QtWidgets.QApplication(sys.argv)
    window = ColormusicApp()
    window.show()

    #print(str(sounddev.query_devices()).split('\n'))

    sound_thread = SoundThread()
    sound_thread.start()

    w = QWidget()
    trayIcon = SystemTrayIcon(QtGui.QIcon("images\\tray.png"), w)
    trayIcon.show()

    app.exec_()  # и запускаем приложение
    
    # Отправляем потокам сообщение о необходимости остановки
    lock_stop_thread.acquire()
    stop_thread = True
    lock_stop_thread.release()
    # Ожидание завершения потока
    sound_thread.join()
    
    window.closeRes()
    window.closeHID()

    saveSettings()

if __name__ == '__main__':
    main()