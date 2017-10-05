# -*- coding: utf-8 -*-
"""
/***************************************************************************
 Threshold
                                 A QGIS plugin
 Adds context controls for brightness and contrast
                             -------------------
        begin                : 2017-07-05
        copyright            : (C) 2017 by Ryan Constantino
        email                : ryan.constantino93@gmail.com
        git sha              : $Format:%H$
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
 This script initializes the plugin, making it known to QGIS.
"""


# noinspection PyPep8Naming
def classFactory(iface):  # pylint: disable=invalid-name
    """Load Threshold class from file Threshold.

    :param iface: A QGIS interface instance.
    :type iface: QgsInterface
    """
    #
    from .threshold_plugin import Threshold
    return Threshold(iface)
