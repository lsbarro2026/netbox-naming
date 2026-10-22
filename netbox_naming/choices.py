from utilities.choices import ChoiceSet


class KindChoices(ChoiceSet):
    key = "NamingConvention.kind"

    STATIC = "static"
    NUMBERED = "numbered"
    TAIL = "tail"

    CHOICES = [
        (STATIC, "Static"),
        (NUMBERED, "Numbered"),
        (TAIL, "Custom tail"),
    ]


class TargetFieldChoices(ChoiceSet):
    key = "NamingConvention.target_field"

    NAME = "name"
    ASSET_TAG = "asset_tag"

    CHOICES = [
        (NAME, "Name"),
        (ASSET_TAG, "Asset tag"),
    ]


class CounterScopeChoices(ChoiceSet):
    key = "NamingConvention.counter_scope"

    GLOBAL = "global"
    SITE = "site"
    LOCATION = "location"

    CHOICES = [
        (GLOBAL, "Global"),
        (SITE, "Per site"),
        (LOCATION, "Per location"),
    ]
