# -*- coding: utf-8 -*-
"""
/***************************************************************************
 Threshold
                                 A QGIS plugin
 Adds context controls for brightness and contrast
                              -------------------
        begin                : 2017-07-05
        git sha              : $Format:%H$
        copyright            : (C) 2017 by Ryan Constantino
        email                : ryan.constantino93@gmail.com
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""
from qgis.core import *
from qgis.gui import *
from PyQt4.QtCore import QSettings, QTranslator, qVersion, QCoreApplication, QTimer, Qt, QThread
from PyQt4.QtGui import *
# Initialize Qt resources from file resources.py
import resources
# Import the code for the dialog
from threshold_plugin_dialog import ThresholdDialog
import os.path
import math
from Worker import Worker
import time

# For @throttle
from datetime import datetime, timedelta
from functools import wraps

class throttle(object):
    """
    Decorator that prevents a function from being called more than once every
    time period.

    To create a function that cannot be called more than once a minute:

        @throttle(minutes=1)
        def my_fun():
            pass
    """
    def __init__(self, seconds=0, minutes=0, hours=0):
        self.throttle_period = timedelta(
            seconds=seconds, minutes=minutes, hours=hours
        )
        self.time_of_last_call = datetime.min

    def __call__(self, fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            now = datetime.now()
            time_since_last_call = now - self.time_of_last_call

            if time_since_last_call > self.throttle_period:
                self.time_of_last_call = now
                return fn(*args, **kwargs)

        return wrapper

class Threshold:
    """QGIS Plugin Implementation."""

    def __init__(self, iface):
        """Constructor.

        :param iface: An interface instance that will be passed to this class
            which provides the hook by which you can manipulate the QGIS
            application at run time.
        :type iface: QgsInterface
        """

        print("__init__ called")
        self.layer = None
        self.fcn = None
        self.shader = None
        self.renderer = None
        self.WHITE = QColor(255, 255, 255)
        self.BLACK = QColor(0, 0, 0)
        self.color_picker = QColorDialog()
        self.color_picker.setOption(QColorDialog.ShowAlphaChannel, on=True)
        self.BASE = QColor(255, 0, 255)
        self.HIGHLIGHT = QColor(255, 255, 255, 0.75)
        self.threshold_current_value = float("-inf")
        self.precision = 2
        self.increment = 1.0 / (10 ** self.precision)
        self.first_run = True
        self.last_time = time.time() * 1000

        # Save reference to the QGIS interface
        self.iface = iface
        # initialize plugin directory
        self.plugin_dir = os.path.dirname(__file__)
        # initialize locale
        locale = QSettings().value('locale/userLocale')[0:2]
        locale_path = os.path.join(
            self.plugin_dir,
            'i18n',
            'Threshold_{}.qm'.format(locale))

        if os.path.exists(locale_path):
            self.translator = QTranslator()
            self.translator.load(locale_path)

            if qVersion() > '4.3.3':
                QCoreApplication.installTranslator(self.translator)


        # Declare instance attributes
        self.actions = []
        self.menu = self.tr(u'&Threshold Plugin')

        self.debounce_timer = QTimer()
        self.debounce_timer.timeout.connect(self.render)
        self.debounce_timer.setSingleShot(True)

        ### SET MIN AND MAX HERE ###
        self.MIN = float("inf")
        self.MAX = float("-inf")
        self.MIN_PROXY = float("inf")
        self.MAX_PROXY = float("-inf")

        # TODO: We are going to let the user set this up in a future iteration
        self.toolbar = self.iface.addToolBar(u'Threshold')
        self.toolbar.setObjectName(u'Threshold')

        self.brightnessFilter = QgsBrightnessContrastFilter()

    # noinspection PyMethodMayBeStatic
    def tr(self, message):
        """Get the translation for a string using Qt translation API.

        We implement this ourselves since we do not inherit QObject.

        :param message: String for translation.
        :type message: str, QString

        :returns: Translated version of message.
        :rtype: QString
        """
        # noinspection PyTypeChecker,PyArgumentList,PyCallByClass
        return QCoreApplication.translate('Threshold', message)


    def add_action(
        self,
        icon_path,
        text,
        callback,
        enabled_flag=True,
        add_to_menu=True,
        add_to_toolbar=True,
        status_tip=None,
        whats_this=None,
        parent=None):
        """Add a toolbar icon to the toolbar.

        :param icon_path: Path to the icon for this action. Can be a resource
            path (e.g. ':/plugins/foo/bar.png') or a normal file system path.
        :type icon_path: str

        :param text: Text that should be shown in menu items for this action.
        :type text: str

        :param callback: Function to be called when the action is triggered.
        :type callback: function

        :param enabled_flag: A flag indicating if the action should be enabled
            by default. Defaults to True.
        :type enabled_flag: bool

        :param add_to_menu: Flag indicating whether the action should also
            be added to the menu. Defaults to True.
        :type add_to_menu: bool

        :param add_to_toolbar: Flag indicating whether the action should also
            be added to the toolbar. Defaults to True.
        :type add_to_toolbar: bool

        :param status_tip: Optional text to show in a popup when mouse pointer
            hovers over the action.
        :type status_tip: str

        :param parent: Parent widget for the new action. Defaults None.
        :type parent: QWidget

        :param whats_this: Optional text to show in the status bar when the
            mouse pointer hovers over the action.

        :returns: The action that was created. Note that the action is also
            added to self.actions list.
        :rtype: QAction
        """

        # Create the dialog (after translation) and keep reference
        self.dlg = ThresholdDialog()

        icon = QIcon(icon_path)
        action = QAction(icon, text, parent)
        action.triggered.connect(callback)
        action.setEnabled(enabled_flag)

        if status_tip is not None:
            action.setStatusTip(status_tip)

        if whats_this is not None:
            action.setWhatsThis(whats_this)

        if add_to_toolbar:
            self.toolbar.addAction(action)

        if add_to_menu:
            self.iface.addPluginToMenu(
                self.menu,
                action)

        self.actions.append(action)

        return action

    def initGui(self):
        """Create the menu entries and toolbar icons inside the QGIS GUI."""

        icon_path = ':/plugins/Threshold/icon.png'
        self.add_action(
            icon_path,
            text=self.tr(u'Threshold'),
            callback=self.run,
            parent=self.iface.mainWindow())


    def unload(self):
        """Removes the plugin menu item and icon from QGIS GUI."""
        for action in self.actions:
            self.iface.removePluginMenu(
                self.tr(u'&Threshold Plugin'),
                action)
            self.iface.removeToolBarIcon(action)
        # remove the toolbar
        del self.toolbar


    def run(self):
        """Run method that performs all the real work"""
        # show the dialog
        self.dlg.show()
        self.toggleWidgets(False)
        self.layer = self.iface.activeLayer()
        if self.layer is None:
            self.dlg.header.setText("No layer selected.")
            return
        else:
            if isinstance(self.layer, QgsRasterLayer) is False:
                self.dlg.header.setText('Expected a QgsRasterLayer')
                return
            self.dlg.header.setText("") # Active layer 
            if not hasattr(self.layer, "hasFilter"):
                self.layer.pipe().set(self.brightnessFilter)
                self.fcn = QgsColorRampShader()
                self.fcn.setColorRampType(QgsColorRampShader.DISCRETE)
                self.layer.hasFilter = True

        ############################
        ### COMMENT OUT STARTING HERE
        if self.MAX == float("-inf"):

            self.startWorker(self.iface, self.layer)
            print("min: {}, max: {}".format(self.MIN, self.MAX))
        else:
            self.toggleWidgets(True)
        ### COMMENT OUT ENDS HERE
        #########################

        self.set_values()

        # Run the dialog event loop
        result = self.dlg.exec_()

        try: 
            self.dlg.base_color_button.clicked.disconnect()
            self.dlg.highlight_color_button.clicked.disconnect()
        except:
            pass

        # See if OK was pressed
        if result:
            # Do something useful here - delete the line containing pass and
            # substitute with your code.
            print ("OK pressed")
        else:
            print ("CANCEL pressed")
    
    def set_values(self):
        # Keyboard Control
        #self.dlg.lineEdit.keyPress.connect(self.on_key_press)
        self.dlg.precision_spinbox.setMinimum(1)
        self.dlg.precision_spinbox.setMaximum(6) # Above 6, integer errors
        self.dlg.precision_spinbox.setValue(self.precision)
        if self.first_run:
            self.dlg.precision_spinbox.valueChanged.connect(self.on_precision_changed)

        self.dlg.threshold_box.setSingleStep(self.increment)
        self.dlg.threshold_box.setDecimals(5)
        self.dlg.threshold_box.setMaximum(self.MAX)
        self.dlg.threshold_box.setMinimum(self.MIN)
        self.dlg.threshold_box.setValue(self.threshold_current_value)
        if self.first_run:
            self.dlg.threshold_box.valueChanged.connect(lambda: self.on_changed("box"))

        self.dlg.base_color_value.setStyleSheet("background-color: {}".format(self.BASE.name()))
        self.dlg.highlight_color_value.setStyleSheet("background-color: {}".format(self.HIGHLIGHT.name()))

        self.dlg.threshold_slider.setMinimum(self.MIN * (10 ** self.precision))
        self.dlg.threshold_slider.setMaximum(self.MAX * (10 ** self.precision))
        # self.dlg.threshold_slider.setValue(self.threshold_current_value * (10 ** self.precision))
        print "min: {}, max: {}, current: {}".format(self.MIN, self.MAX, self.threshold_current_value)
        if self.first_run:
            self.dlg.threshold_slider.valueChanged.connect(lambda: self.on_changed("slider"))

        if self.first_run:
            self.dlg.base_color_button.clicked.connect(self.on_base_clicked)
            self.dlg.highlight_color_button.clicked.connect(self.on_highlight_clicked)

        self.dlg.base_color_alpha_slider.setMinimum(0)
        self.dlg.base_color_alpha_slider.setMaximum(255)
        self.dlg.base_color_alpha_slider.setValue(self.BASE.alpha())
        if self.first_run:
            self.dlg.base_color_alpha_slider.valueChanged.connect(lambda: self.on_changed("alpha"))

        self.dlg.highlight_color_alpha_slider.setMinimum(0)
        self.dlg.highlight_color_alpha_slider.setMaximum(255)
        self.dlg.highlight_color_alpha_slider.setValue(self.HIGHLIGHT.alpha())
        if self.first_run:
            self.dlg.highlight_color_alpha_slider.valueChanged.connect(lambda: self.on_changed("alpha"))
        
        self.first_run = False

    def on_threshold_box_changed(self, value):
        print "value: {}".format(value)

    def on_base_alpha_changed(self):
        alpha = self.dlg.base_color_alpha_slider.value()
        self.BASE.setAlpha(alpha)
        # self.dlg.base_color_value.setText(str(self.BASE.getRgb()))
        self.dlg.base_color_value.setStyleSheet("background-color: {}".format(self.BASE.name()))
        pass

    def on_highlight_alpha_changed(self):
        alpha = self.dlg.highlight_color_alpha_slider.value()
        self.HIGHLIGHT.setAlpha(alpha)
        # self.dlg.highlight_color_value.setText(str(self.HIGHLIGHT.getRgb()))
        self.dlg.highlight_color_value.setStyleSheet("background-color: {}".format(self.BASE.name()))
        pass

    def on_base_clicked(self):
        print("Base Clicked!")
        self.BASE = self.color_picker.getColor(self.BASE)
        # self.dlg.base_color_value.setText(str(self.BASE.getRgb()))
        self.dlg.base_color_value.setStyleSheet("background-color: {}".format(self.BASE.name()))
        self.color_picker.done(0)
        self.on_changed(None)

    def on_highlight_clicked(self):
        print("Highlight Clicked!")
        self.HIGHLIGHT = self.color_picker.getColor(self.HIGHLIGHT)
        # self.dlg.highlight_color_value.setText(str(self.HIGHLIGHT.getRgb()))
        self.dlg.highlight_color_value.setStyleSheet("background-color: {}".format(self.BASE.name()))
        self.color_picker.done(0)
        self.on_changed(None)

    def render(self):
        lst = [QgsColorRampShader.ColorRampItem(self.threshold_current_value, self.HIGHLIGHT), QgsColorRampShader.ColorRampItem(255, self.BASE)]
        self.fcn = QgsColorRampShader()
        self.fcn.setColorRampType(QgsColorRampShader.DISCRETE) 
        self.fcn.setColorRampItemList(lst)
        self.shader = QgsRasterShader()
        
        self.shader.setRasterShaderFunction(self.fcn)

        self.renderer = QgsSingleBandPseudoColorRenderer(self.layer.dataProvider(), 1, self.shader)
        
        self.layer.setRenderer(self.renderer)
        self.layer.triggerRepaint()

    def on_precision_changed(self):
        self.precision = self.dlg.precision_spinbox.value()
        self.increment = 1.0 / (10 ** self.precision)
        self.dlg.threshold_box.setSingleStep(self.increment)
        self.set_values()

    def on_changed(self, source):
        if (time.time()*1000 - self.last_time) < 25:
            return
        else:
            self.last_time = time.time() * 1000
            print "Proceeding"
        # brightness = self.dlg.brightness_slider.value()
        # contrast = self.dlg.contrast_slider.value()
        # self.dlg.brightness_value.setText(str(brightness))
        # self.dlg.contrast_value.setText(str(contrast))
        # self.brightnessFilter.setBrightness(brightness)
        # self.brightnessFilter.setContrast(contrast)

        base_alpha = self.dlg.base_color_alpha_slider.value()
        self.BASE.setAlpha(base_alpha)
        # self.dlg.base_color_value.setText(str(self.BASE.getRgb()))
        self.dlg.base_color_value.setStyleSheet("background-color: {}".format(self.BASE.name()))

        highlight_alpha = self.dlg.highlight_color_alpha_slider.value()
        self.HIGHLIGHT.setAlpha(highlight_alpha)
        # self.dlg.highlight_color_value.setText(str(self.HIGHLIGHT.getRgb()))
        self.dlg.highlight_color_value.setStyleSheet("background-color: {}".format(self.HIGHLIGHT.name()))

        threshold_value = 0
        if source == "slider":
            threshold_value = (self.dlg.threshold_slider.value() / (10.0 ** self.precision))
        elif source == "box":
            threshold_value = self.dlg.threshold_box.value()

        self.dlg.threshold_slider.setValue(threshold_value * (10 ** self.precision))
        self.dlg.threshold_box.setValue(threshold_value)
        # self.dlg.threshold_value.setText(str(threshold_value))
        self.threshold_current_value = threshold_value

        # intiate render() 
        if source == "box":
            self.debounce_timer.start(10)
        else:
            self.debounce_timer.start(50)

    def toggleWidgets(self, value):
        self.dlg.threshold_box.setEnabled(value)
        self.dlg.threshold_slider.setEnabled(value)
        self.dlg.base_color_button.setEnabled(value)
        self.dlg.highlight_color_button.setEnabled(value)
        self.dlg.base_color_alpha_slider.setEnabled(value)
        self.dlg.highlight_color_alpha_slider.setEnabled(value)
        pass

    def startWorker(self, iface, layer):
        worker = Worker(iface, layer)
        messageBar = self.iface.messageBar().createMessage('Calculating range...', )
        progressBar = QProgressBar()
        progressBar.setAlignment(Qt.AlignLeft|Qt.AlignVCenter)
        cancelButton = QPushButton()
        cancelButton.setText('Cancel')
        cancelButton.clicked.connect(worker.kill)
        messageBar.layout().addWidget(progressBar)
        messageBar.layout().addWidget(cancelButton)
        self.iface.messageBar().pushWidget(messageBar, self.iface.messageBar().INFO)
        self.messageBar = messageBar

        #start the worker in a new thread
        thread = QThread()
        worker.moveToThread(thread)
        worker.finished.connect(self.workerFinished)
        worker.error.connect(self.workerError)
        worker.progress.connect(progressBar.setValue)
        thread.started.connect(worker.run)
        thread.start()
        self.thread = thread
        self.worker = worker
        pass

    def workerFinished(self, ret):
        # clean up the worker and thread
        self.worker.deleteLater()
        self.thread.quit()
        self.thread.wait()
        self.thread.deleteLater()
        # remove widget from message bar
        self.iface.messageBar().popWidget(self.messageBar)
        if ret is not None:
            # report the result
            _min, _max = ret
            self.MIN = _min
            self.MAX = _max
            self.set_values()
            self.toggleWidgets(True)

            # self.iface.messageBar().pushMessage('min: {}, max: {}'.format(_min, _max))
        else:
            # notify the user that something went wrong
            self.iface.messageBar().pushMessage('Something went wrong! See the message log for more information.', level=QgsMessageBar.CRITICAL, duration=3)
    
    def workerError(self, e, exception_string):
        raise Exception("workerError {}".format(exception_string))
        pass
        # QgsMessageLog.logMessage('Worker thread raised an exception:\n'.format(exception_string), level=QgsMessageLog.CRITICAL)
