from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler


REQUIRED_MESSAGES = {
    "this field is required.",
    "this field may not be blank.",
    "this field may not be null.",
}


CONSTRAINT_MESSAGES = {
    # TODO, example: "error_insert_location": "Location you have inserted is not correct",
}


def custom_exception_handler(exc, context):
    if isinstance(exc, IntegrityError):
        return Response(
            format_integrity_error(exc),
            status=status.HTTP_400_BAD_REQUEST,
        )

    if isinstance(exc, DjangoValidationError):
        return Response(
            {
                "message": "Validation failed.",
                "errors": normalize_error_detail(
                    getattr(exc, "message_dict", None) or exc.messages
                ),
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    response = exception_handler(exc, context)
    if response is None:
        return None

    if response.status_code == status.HTTP_400_BAD_REQUEST:
        response.data = format_validation_error(response.data)
    elif isinstance(response.data, dict) and "detail" in response.data:
        response.data = {
            "message": str(response.data["detail"]),
            "errors": normalize_error_detail(response.data),
        }
    return response


def format_validation_error(data):
    errors = normalize_error_detail(data)
    required_fields = find_required_fields(data)
    if required_fields:
        field_list = human_join(required_fields)
        return {
            "message": f"You forgot to send {field_list}.",
            "required_fields": required_fields,
            "errors": errors,
        }
    return {
        "message": "Validation failed.",
        "errors": errors,
    }


def find_required_fields(data, prefix=""):
    fields = []
    if isinstance(data, dict):
        for field, value in data.items():
            path = f"{prefix}.{field}" if prefix else str(field)
            if is_required_error(value):
                fields.append(path)
            else:
                fields.extend(find_required_fields(value, path))
    elif isinstance(data, list):
        for index, value in enumerate(data):
            fields.extend(find_required_fields(value, f"{prefix}[{index}]"))
    return fields


def is_required_error(value):
    if isinstance(value, (list, tuple)):
        return any(is_required_error(item) for item in value)
    message = str(value).strip().lower()
    code = getattr(value, "code", "")
    return code in {"required", "blank", "null"} or message in REQUIRED_MESSAGES


def normalize_error_detail(data):
    if isinstance(data, dict):
        return {key: normalize_error_detail(value) for key, value in data.items()}
    if isinstance(data, list):
        return [normalize_error_detail(value) for value in data]
    return str(data)


def format_integrity_error(exc):
    diag = getattr(getattr(exc, "__cause__", None), "diag", None)
    constraint_name = getattr(diag, "constraint_name", "") if diag else ""
    column_name = getattr(diag, "column_name", "") if diag else ""

    if constraint_name and constraint_name in CONSTRAINT_MESSAGES:
        return {
            "message": CONSTRAINT_MESSAGES[constraint_name],
            "constraint": constraint_name,
            "errors": {"non_field_errors": [CONSTRAINT_MESSAGES[constraint_name]]},
        }

    if column_name:
        message = f"Invalid value for {column_name}."
        return {
            "message": message,
            "errors": {column_name: [message]},
        }

    message = "Invalid data. A database constraint was violated."
    return {
        "message": message,
        "errors": {"non_field_errors": [message]},
    }


def human_join(values):
    if len(values) == 1:
        return values[0]
    if len(values) == 2:
        return f"{values[0]} and {values[1]}"
    return f"{', '.join(values[:-1])}, and {values[-1]}"


class CrossUserConflict(Exception):
    """A client-supplied record id already belongs to a different user."""

    def __init__(self, record_id):
        self.record_id = record_id
        super().__init__(f"Record {record_id} belongs to another user.")
