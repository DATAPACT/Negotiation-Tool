from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("custom_accounts", "0024_alter_consentrequestformsendtouser_consent_given_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="mongo_id",
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
    ]
