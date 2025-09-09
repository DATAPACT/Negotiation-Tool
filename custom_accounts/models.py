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



from django.contrib.auth.models import AbstractUser
from django.db import models
from django_currentuser.db.models import CurrentUserField

"""
DATA_PROVIDER: The term data provider here represent the data subject in GDPR terminology, who owns or produce the data.
DATACONTROLLER_PROCESSOR: The term data controller and data processor here represent the data controller and data processor in GDPR terminology, who process the data from the data subject or the other data controller, i.e., process on the behalf of another controller.
"""
USER_TYPES = (
    ("DATA_PROVIDER", "Data Subject/Data Provider"),
    ("DATACONTROLLER_PROCESSOR", "Data Contact/Data Processor"),
    # ("ADMIN", "Admin"),
)

CONSENT_FORM_DELETE_STATUS = (("ACTIVE", "Active"), ("DELETED", "Deleted"))

USER_CONSENT_ANSWER_STATUS = (
    ("REQUESTED", "Requested"),
    ("RESPONDED", "Responded"),
    ("REVOKED", "Revoked"),
)

REQUEST_STATUS = (("SENT", "Sent"), ("CREATED", "Created"))

ONTOLOGY_TYPES_CHOICES = (
    ("DATA_CONTEXT", "Data and Context Information Ontology"),
    ("CONSENT", "Consent Ontology with Purpose and Data Processing Operations"),
    ("CUSTOM_CONSTANT", "Use case specific privacy constraints ontology"),
)


class User(AbstractUser):
    role = models.CharField(default="DATA_PROVIDER", choices=USER_TYPES, max_length=100)
    mongo_id = models.CharField(max_length=50, blank=True, null=True)

class OntologyUpload(models.Model):
    id = models.IntegerField(primary_key=True)
    name = models.CharField(max_length=60)
    file = models.FileField(upload_to="ontology/")
    ontology_type = models.CharField(max_length=150, default="DATA_CONTEXT")
    created_by = CurrentUserField(related_name="fileuploadsby")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class SensorData(models.Model):
    """Model definition for SensorData. This is the master table for the sensor data.

    This model defines the field to provide information about the sensors or data that the data subject have.
    """

    id = models.IntegerField(primary_key=True)
    sensor_data = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class DataSubjectData(models.Model):
    """Model definition for DataSubjectData. This is the master table for the data subject data.

    This model defines the field to provide information about the data subject data.
    """

    id = models.IntegerField(primary_key=True)
    data_subject_data = models.CharField(max_length=255)
    consent_status = models.BooleanField()
    consent_given_date = models.DateField()
    consent_revoked_date = models.DateField(null=True, blank=True)
    consent_given_by = models.CharField(max_length=255)  # store the user ID
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class ConsentRequest(models.Model):
    id = models.IntegerField(primary_key=True)
    consent_requested_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="consent_requested_by"
    )
    assignee = models.ManyToManyField(User, related_name="assignee")
    consent_request_form_title = models.CharField(
        max_length=455, default="Consent Request Form"
    )
    general_ontology = models.CharField(max_length=255)
    domain_ontology = models.CharField(max_length=255)
    schema_ontology = models.CharField(max_length=255)
    consent_data = models.CharField(max_length=255)
    consent_purpose = models.CharField(max_length=255)
    consent_operations = models.JSONField(default="{}")
    consent_date_start = models.DateField()
    consent_date_end = models.DateField()
    additional_requests = models.JSONField(default="{}")
    consent_request_sent_status = models.CharField(
        default="CREATED", max_length=55, choices=REQUEST_STATUS
    )
    consent_form_delete_status = models.CharField(
        default="ACTIVE", max_length=55, choices=CONSENT_FORM_DELETE_STATUS
    )
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = CurrentUserField(related_name="consent_request_created_by")
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def create(cls, data):
        """This is to be used in the future for provenance purpose. For now, we are not considering it as it requires
        discussion  and some design changes. For example, currently, we are allowing the deletion of the uploaded
        ontology, which should be disabled when we want to keep the provenance than just saying which ontology was used.
        It can be thought of as a version control for ontology.
        Why it's important?
        1. Helps to track which ontology was used and also track the contents of the ontology.
        2. This also means that we need to consider about the storage and dealing with it. As overtime, we will have
        large number of different ontologies, maybe with just small changes.
        """
        # cls.general_ontology = data["general_ontology"]
        # cls.domain_ontology = data["domain_ontology"]
        # cls.schema_ontology = data["schema_ontology"]
        consent_requested_by = User.objects.get(id=data["consent_requested_by"])
        consent_request = cls(
            consent_requested_by=consent_requested_by,
            general_ontology=data.get("general_ontology", ""),
            domain_ontology=data.get("domain_ontology", ""),
            schema_ontology=data.get("schema_ontology", ""),
            consent_data=data.get("consent_data", ""),
            consent_purpose=data["consent_purpose"],
            consent_request_form_title=data["consentformname"],
            consent_operations=data["consent_operations"],
            consent_date_start=data["consent_date_start"],
            consent_date_end=data["consent_date_end"],
            additional_requests=data.get("rule", {}),
        )
        consent_request.save()  # Save the data to the database


class ConsentRequestFormSendToUser(models.Model):
    id = models.IntegerField(primary_key=True)
    consent_requestform = models.ForeignKey(
        ConsentRequest, on_delete=models.PROTECT, related_name="consent_request"
    )
    consent_request_form_sent_to = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="consent_request_form_sent_to"
    )
    consent_answer_status = models.CharField(
        default="REQUESTED", choices=USER_CONSENT_ANSWER_STATUS, max_length=100
    )
    consent_given_status = models.CharField(max_length=100, default="Requested")
    additional_constraints = models.JSONField()

    created_at = models.DateTimeField(auto_now_add=True)
    sent_by = CurrentUserField(related_name="consent_request_form_sent_by")
    updated_at = models.DateTimeField(auto_now=True)


class ConsentRequestFormResponseODRL(models.Model):
    id = models.IntegerField(primary_key=True)
    consentrequestsendtouserformid = models.ForeignKey(
        ConsentRequestFormSendToUser,
        on_delete=models.PROTECT,
        related_name="consent_request_sent_to_user_form",
    )
    odrl_consent_additional_constraints = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    data_controller_processor_id = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="consent_requested_by_controller_processor",
    )
    consented_by_user = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="consented_given_by_user",
    )
