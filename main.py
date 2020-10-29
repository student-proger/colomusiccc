'''
* Author:         Gladyshev Dmitriy (2020) 
* 
* Design Name:    ColormusicCC
* Description:    Программа для управления цветомузыкой
'''

__version__ = "0.0.1a"

import os
import sys
import time

import math

import numpy as np
import sounddevice as sd

from pywinusb import hid
# https://sourceforge.net/projects/libusb-win32/files/libusb-win32-releases/1.2.6.0/

from threading import Thread, Lock

import pygame
import pygame.midi
from pygame.locals import *

#Qt
from PyQt5 import QtWidgets, QtCore
from PyQt5.QtWidgets import QTableWidgetItem, QLabel, QTimeEdit, QInputDialog, QComboBox
from PyQt5.QtWidgets import QMessageBox
from PyQt5.QtGui import QPixmap
from PyQt5.QtGui import QPainter, QColor, QBrush, QFont
from PyQt5.QtCore import Qt, QRect
#design
import mainform

RED = 0
GREEN = 1
BLUE = 2

butt = {
    "OnOff": [10, 10, 50, 20, "ON", False],
    "AutoGain": [80, 10, 90, 20, "Auto gain", False],
    "LogComp": [180, 10, 90, 20, "Comp", False]
}

buttPress = {
    "agbvPlus": [150, 35, 20, 20, "+", False],
    "agbvMinus": [80, 35, 20, 20, "-", False]
}

columns = 60


print(sd.query_devices())

device = None
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





class MidiThread(Thread):
    def __init__(self):
        Thread.__init__(self)

    def run(self):
        print("Start MIDI thread")
        self.input_main()
        print("MIDI stop thread")

    def _print_device_info(self):
        for i in range( pygame.midi.get_count() ):
            r = pygame.midi.get_device_info(i)
            (interf, name, input, output, opened) = r

            in_out = ""
            if input:
                in_out = "(input)"
            if output:
                in_out = "(output)"

            print ("%2i: interface :%s:, name :%s:, opened :%s:  %s" %
                   (i, interf, name, opened, in_out))

    def input_main(self, device_id = None):
        
        event_get = pygame.fastevent.get
        event_post = pygame.fastevent.post

        pygame.midi.init()

        self._print_device_info()


        if device_id is None:
            input_id = pygame.midi.get_default_input_id()
        else:
            input_id = device_id

        print ("using input_id :%s:" % input_id)
        i = pygame.midi.Input( input_id )

        while True:
            time.sleep(0.1)
            events = event_get()
            for e in events:
                if e.type in [pygame.midi.MIDIIN]:
                    print (e)

            if i.poll():
                midi_events = i.read(10)
                # convert them into pygame events.
                midi_evs = pygame.midi.midis2events(midi_events, i.device_id)

                for m_e in midi_evs:
                    event_post( m_e )
            lock_stop_thread.acquire()
            if stop_thread:
                lock_stop_thread.release()
                break
            lock_stop_thread.release()

        i.close()
        pygame.midi.quit()
        

class SoundThread(Thread):
    def __init__(self):
        Thread.__init__(self)
    
    def run(self):
        global gain
        """Запуск потока"""
        try:
            samplerate = sd.query_devices(device, 'input')['default_samplerate']

            delta_f = (high - low) / (columns - 1)
            fftsize = math.ceil(samplerate / delta_f)
            low_bin = math.floor(low / delta_f)

            def callback(indata, frames, time, status):
                global spectrum
                global leftLevel
                global rightLevel
                #print(indata[:, 1])
                if status:
                    text = '************************ ' + str(status) + ' ************************'
                    print(text)
                #if any(indata[0]):
                magnitude = np.abs(np.fft.rfft(indata[:, 0], n=fftsize))
                magnitude *= gain / fftsize

                leftspectrum = []
                for x in magnitude[low_bin:low_bin + columns]:
                    leftspectrum.append(round(x * 100000))
                magnitude = np.abs(np.fft.rfft(indata[:, 1], n=fftsize))
                magnitude *= gain / fftsize

                rightspectrum = []
                for x in magnitude[low_bin:low_bin + columns]:
                    rightspectrum.append(round(x * 100000))

                lock_spectrum.acquire()
                leftLevel = max(leftspectrum)
                rightLevel = max(rightspectrum)
                spectrum = []
                for i in range(0, len(leftspectrum)):
                    spectrum.append(max(leftspectrum[i], rightspectrum[i]))
                lock_spectrum.release()

            with sd.InputStream(device=device, channels=2, callback=callback,
                                blocksize=int(samplerate * block_duration / 1000),
                                samplerate=samplerate):
                while True:
                    time.sleep(1)
                    lock_stop_thread.acquire()
                    if stop_thread:
                        lock_stop_thread.release()
                        break
                    lock_stop_thread.release()

        except KeyboardInterrupt:
            print('Interrupted by user')
        except Exception as e:
            print(type(e).__name__ + ': ' + str(e))


class ColormusicApp(QtWidgets.QMainWindow, mainform.Ui_MainWindow):
    def __init__(self):
        super().__init__()
        self.setupUi(self)  # Это нужно для инициализации нашего дизайна

        self.Mode = 1

        self.leds = []
        for i in range(0, 10):
            self.leds.append([0, 0, 0])

        self.spectrum = [0] * columns

        self.maxvalue = 1
        self.lastMaxPeakTime = time.time()

        self.agBurstValue = 0

        #Главный таймер
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.on_timer)
        self.timer.start(20)

        self.pushButton.pressed.connect(self.testbutton)

        self.openHID(vid = 0x1EAF, pid = 0x0028)
        
    def testbutton(self):
        pass

    #Отправка данных на USB HID устройство
    def writeHID(self):
        buf = [0x00]

        for item in self.leds:
            for k in item:
                buf.append(k)

        try:
            self.out_report.set_raw_data(buf)
            self.out_report.send()
        except AttributeError:
            return

    #Открытие USB HID устройства для работы
    def openHID(self, vid, pid):
        filter = hid.HidDeviceFilter(vendor_id = vid, product_id = pid)
        devices = filter.get_devices()
        if devices:
            self.device = devices[0]
            print("USB device founded.")
            self.device.open()
            
            self.out_report = self.device.find_output_reports()[0]

    #Закрытие USB HID устройства
    def closeHID(self):
        buf = [0x00] * 31
        try:
            self.out_report.set_raw_data(buf)
            self.out_report.send()
            self.device.close()
        except AttributeError:
            return

    #Событие нажатия кнопки мыши
    def mousePressEvent(self, QMouseEvent):
        xx = QMouseEvent.x()
        yy = QMouseEvent.y()
        for item in butt:
            x, y = butt[item][0], butt[item][1]
            w, h = butt[item][2], butt[item][3]
            if (xx >= x) and (xx < x + w) and (yy >= y) and (yy < y + h):
                butt[item][5] = not butt[item][5]

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

    #Событие отпускания кнопки мыши
    def mouseReleaseEvent(self, QMouseEvent):
        xx = QMouseEvent.x()
        yy = QMouseEvent.y()
        for item in buttPress:
            if buttPress[item][5]:
                buttPress[item][5] = False

    """Обработчик события главного таймера.
    Таймер вызывается каждые 20 мс. Здесь происходит обработка данных спектра,
    выполнение алгоритма переключения светодиодов и отрисовка GUI.
    """
    def on_timer(self):
        global spectrum

        lock_spectrum.acquire()
        self.spectrum = []
        for x in spectrum:
            self.spectrum.append(x)
        lock_spectrum.release()

        if len(self.spectrum) != columns:
            self.spectrum = [0] * columns

        self.update()

        #Auto gain
        if butt["AutoGain"][5]:
            if time.time() - self.lastMaxPeakTime > 15:
                self.maxvalue = 1

            maxs = max(self.spectrum)
            if maxs > self.maxvalue:
                self.maxvalue = maxs
                self.lastMaxPeakTime = time.time()
            gainCorrection = ((self.agBurstValue / 100) * 1000 + 1000) / self.maxvalue
            for i in range(0, columns):
                self.spectrum[i] = self.spectrum[i] * gainCorrection
        #==========================


        #Логарифмический компрессор
        if butt["LogComp"][5]:
            for i in range(0, columns):
                try:
                    self.spectrum[i] = ((self.agBurstValue / 100) * 1000 + 1000) * (1 / math.log10(1000 / 50)) * math.log10(self.spectrum[i] / 50)
                    if self.spectrum[i] < 0:
                        self.spectrum[i] = 0
                except ValueError:
                    self.spectrum[i] = 0
        #==========================

        if self.Mode == 1:
            self.processMode1()

        self.writeHID()

    #Обработчик перерисовки формы
    def paintEvent(self, e):
        qp = QPainter()
        qp.begin(self)
        self.drawUI(qp)
        qp.end()

    #Рисует пустой прямоугольник
    def drawSimpleRect(self, qp, x1, y1, x2, y2):
        qp.drawLine(x1, y1, x2, y1)
        qp.drawLine(x2, y1, x2, y2)
        qp.drawLine(x2, y2, x1, y2)
        qp.drawLine(x1, y2, x1, y1)

    #Рисуем GUI
    def drawUI(self, qp):
        activeColor = QColor(234, 237, 242)
        bgColor = QColor(39, 72, 135)

        #Фон
        qp.setPen(bgColor)
        qp.setBrush(bgColor)
        qp.drawRect(0, 0, 700, 200)

        #Рамки
        qp.setPen(activeColor)
        self.drawSimpleRect(qp, 48, 60, 652, 164)
        self.drawSimpleRect(qp, 11, 60, 35, 164)

        #Спектр сигнала
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

        #Рисуем кнопки
        for item in butt:
            x, y = butt[item][0], butt[item][1]
            w, h = butt[item][2], butt[item][3]
            if butt[item][5]:
                qp.setBrush(activeColor)
            else:
                qp.setBrush(bgColor)
            qp.setPen(activeColor)
            qp.drawRect(x, y, w, h)

            if butt[item][5]:
                qp.setPen(bgColor)
            else:
                qp.setPen(activeColor)
            qp.setFont(QFont('Arial', 10))
            qp.drawText(QRect(x, y, w, h), Qt.AlignCenter, butt[item][4])

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

        #Надписи
        qp.setPen(activeColor)
        qp.setFont(QFont('Arial', 10))
        qp.drawText(QRect(100, 35, 50, 20), Qt.AlignCenter, str(self.agBurstValue) + "%")

    def processMode1(self):
        if len(self.spectrum) == 0:
            return
        ch = [0, 0, 0, 0, 0]
        ch[0] = max(self.spectrum[0:2])
        ch[1] = max(self.spectrum[2:4])
        ch[2] = max(self.spectrum[4:8])
        ch[3] = max(self.spectrum[8:14])
        ch[4] = max(self.spectrum[14:30])

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
            elif ch[i] > 500:
                self.leds[i][BLUE] = 255

        for i in range(0, 5):
            self.leds[9 - i][RED] = self.leds[i][RED]
            self.leds[9 - i][GREEN] = self.leds[i][GREEN]
            self.leds[9 - i][BLUE] = self.leds[i][BLUE]
        

    def processMode2(self):
        pass
        #красные лампы — низкие частоты (диапазон до 200 Гц),
        #жёлтые — средне-низкие (диапазон от 200 до 800 Гц),
        #зелёные — средние (от 800 до 3500 Гц),
        #синие — выше 3500 Гц



def main():
    global stop_thread

    app = QtWidgets.QApplication(sys.argv)  # Новый экземпляр QApplication
    window = ColormusicApp()  # Создаём объект класса SchoolRingerApp
    window.show()  # Показываем окно

    #MIDI init
    pygame.init()
    pygame.fastevent.init()


    pygame.midi.init()
    '''if device_id is None:
        port = pygame.midi.get_default_output_id()
    else:
        port = device_id'''
    port = 3
    print ("using output_id :%s:" % port)
    midi_out = pygame.midi.Output(port, 0)
    '''midi_out.set_instrument(2)
    midi_out.note_on(144, 2)
    time.sleep(2)
    midi_out.note_off(56)'''
    midi_out.close()
    

    sound_thread = SoundThread()
    sound_thread.start()

    midi_thread = MidiThread()
    midi_thread.start()

    

    app.exec_()  # и запускаем приложение

    

    lock_stop_thread.acquire()
    stop_thread = True
    lock_stop_thread.release()
    sound_thread.join()
    midi_thread.join()

    
    #del midi_out
    pygame.midi.quit()

    window.closeHID()

if __name__ == '__main__':
    main()