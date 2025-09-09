# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# DISCLAIMER: This software is provided "as is" without any warranty,
# express or implied, including but not limited to the warranties of
# merchantability, fitness for a particular purpose, and non-infringement.
#
# In no event shall the authors or copyright holders be liable for any
# claim, damages, or other liability, whether in an action of contract,
# tort, or otherwise, arising from, out of, or in connection with the
# software or the use or other dealings in the software.
# -----------------------------------------------------------------------------

# @Author  : Tek Raj Chhetri
# @Email   : tekraj.chhetri@cair-nepal.org
# @Web     : https://tekrajchhetri.com/
# @File    : predictions.py
# @Software: PyCharm


# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# DISCLAIMER: This software is provided "as is" without any warranty,
# express or implied, including but not limited to the warranties of
# merchantability, fitness for a particular purpose, and non-infringement.
#
# In no event shall the authors or copyright holders be liable for any
# claim, damages, or other liability, whether in an action of contract,
# tort, or otherwise, arising from, out of, or in connection with the
# software or the use or other dealings in the software.
# -----------------------------------------------------------------------------

# @Time    : 30.12.23 14:44
# @Author  : Tek Raj Chhetri
# @Email   : tekraj.chhetri@sti2.at
# @Web     : https://tekrajchhetri.com/
# @File    : predictions.py
# @Software: PyCharm

import warnings

warnings.filterwarnings("ignore")


def prettyfy(inputstr, makelower=True):
    return inputstr.split(".")[1].lower() if makelower else inputstr.split(".")[1]


def ontology_classes_dict(ontology):
    """Returns a dictionary of ontology classes

    :param ontology: OWL Ontology
    :return: dictionary of ontology classes
    :rtype: dict
    """
    ontology_class = {}
    for cls in list(ontology.classes()):
        ontology_class[prettyfy(str(cls))] = cls
    return ontology_class


def ontology_objectproperties_dict(ontology):
    """Returns a dictionary of ontology object properties

    :param ontology: OWL Ontology
    :return: dictionary of ontology object properties
    :rtype: dict
    """
    ontology_objprop = {}
    for props in list(ontology.properties()):
        ontology_objprop[prettyfy(str(props))] = props
    return ontology_objprop
