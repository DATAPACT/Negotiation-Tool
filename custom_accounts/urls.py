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


from django.urls import path
from . import views

from django.urls import path

urlpatterns = [
    path('get_text_diff/', views.get_text_diff, name='get_text_diff'),
    # path("user/home", views.userhome, name="userhome"),
    path("organization/home", views.datacontrollerhome, name="datacontrollerhome"),
    path(
        "organization/negotiation",
        views.negotiation,
        name="datacontrollernegotiation",
    ),
    path(
        "save-signature/",
        views.save_signature,
        name="datacontrollersavesignature",
    ),

    path(
        "organization/getnegotiations",
        views.get_negotiations,
        name="datacontrollergetnegotiations",
    ),
        path(
        "organization/get_properties_of_a_class",
        views.ajax_get_properties_of_a_class,
        name="get_properties_of_a_class",
    ),
    path(
        "organization/get_constraints_for_instances",
        views.ajax_get_constraints_for_instances,
        name="get_constraints_for_instances",
    ),
        
    path(
        "organization/updatenegotiation",
        views.updatenegotiation,
        name="datacontrollerupdatenegotiation",
    ),
    path(
        "organization/offer",
        views.get_offer,
        name="datacontrollergetoffer",
    ),
    path(
        "organization/negotiationlastpolicy",
        views.get_negotiation_last_policy,
        name="datacontrollergetnegotiationlastpolicy",
    ),
    path(
        "organization/createpolicy",
        views.create_policy,
        name="datacontrollercreatepolicy",
    ),
        path(
        "organization/createpolicyfromupload",
        views.create_policy_from_upload,
        name="datacontrollercreatepolicyfromupload",
    ),
    path(
        "organization/updatepolicy",
        views.update_policy,
        name="datacontrollerupdatepolicy",
    ),
    path(
        "organization/createagentrecord",
        views.create_agent_record,
        name="datacontrollercreateagentrecord",
    ),
    path(
        "organization/getagentrecord",
        views.get_agent_record,
        name="datacontrollergetagentrecord",
        ),
    # path(
    #     "organization/configured-consent-contract-privacy-preference-request-list",
    #     views.configuredprivacylists,
    #     name="datacontrollerconfiguredprivacylists",
    # ),
    # path(
    #     "organization/convert_to_odrl_login",
    #     views.convert_to_odrl_login,
    #     name="convert_to_odrl_login",
    # ),
    path(
        "organization/ajax_get_fields_from_datasets",
        views.ajax_get_fields_from_datasets,
        name="ajax_get_fields_from_datasets",
    ),
    path(
        "organization/ajax_get_properties_from_properties_file",
        views.ajax_get_properties_from_properties_file,
        name="ajax_get_properties_from_properties_file",
    ),
    # path(
    #     "organization/get_purpose_processing_data_ajax",
    #     views.get_purpose_processing_data_ajax,
    #     name="get_purpose_processing_data_ajax",
    # ),
    # path(
    #     "organization/ajax_use_case_ontology_classes",
    #     views.ajax_use_case_ontology_classes,
    #     name="ajax_use_case_ontology_classes",
    # ),
    # path(
    #     "organization/submit_consent_form",
    #     views.submit_consent_form,
    #     name="submit_consent_form",
    # ),
    # path(
    #     "organization/send_consent_to_selected_user",
    #     views.send_consent_to_selected_user,
    #     name="send_consent_to_selected_user",
    # ),
    # path(
    #     "create-rule",
    #     views.create_rule_dataset_no_user,
    #     name="create_rule_dataset_no_user",
    # ),
    # path(
    #     "create-logic",
    #     views.extract_logic_expressions_page,
    #     name="extract_logic_expressions_page",
    # ),
    # path(
    #     "extract_logic_expressions",
    #     views.extract_logic_expressions,
    #     name="extract_logic_expressions",
    # ),
    # path(
    #     "user/user-sensor-data-profile", views.userdataprofile, name="userdataprofile"
    # ),
    # path("organization/save-consent", views.saveconsent, name="saveconsent"),
    # path("organization/ontology-upload", views.uploadontology, name="uploadontology"),
    # path("organization/view-ontology/", views.viewontology, name="viewontology"),
    # path(
    #     "organization/delete-ontology/<int:ontology_id>",
    #     views.deleteontology,
    #     name="deleteontology",
    # ),
    # path(
    #     "organization/view-consent-form/<int:consent_form_id>",
    #     views.view_consent_form,
    #     name="view_consent_form",
    # ),
    # path(
    #     "organization/delete-deleteconsentrequestform/<int:consentform_id>",
    #     views.deleteconsentrequestform,
    #     name="deleteconsentrequestform",
    # ),
    # path(
    #     "user/consent-request",
    #     views.view_consent_request_user,
    #     name="view_consent_request_user",
    # ),
    # path(
    #     "user/consent-request-user/<int:consent_request_id>",
    #     views.view_consent_request_user_single,
    #     name="view_consent_request_user_single",
    # ),
    path("login", views.signin, name="login"),
    path("logout", views.signout, name="logout"),
    # path("activate/<uidb64>/<token>", views.activate, name="activate"),
    path("sign-up", views.register, name="register"),
    path("auto-login", views.auto_login, name="autologin"),
    path("auto-login-session", views.set_auto_login_session, name="auto_login_session"),
    # path(
    #     "user/save_user_consent_response",
    #     views.save_user_consent_response_data,
    #     name="save_user_consent_response",
    # ),
    # path(
    #     "user/view-user-consent-response-odrl",
    #     views.view_responses_controller_processor_odrl,
    #     name="view_responses_controller_processor_odrl",
    # ),
    # path(
    #     "user/view-user-consent-response-odrl/<int:odrl_id>",
    #     views.view_responses_controller_processor_odrl_single,
    #     name="view_responses_controller_processor_odrl_single",
    # ),
    path("", views.index, name="index"),
]
