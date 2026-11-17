"""Errors safe to present through every interface."""


class ForgeError(Exception):
    status_code = 400


class NotFound(ForgeError):
    status_code = 404


class Conflict(ForgeError):
    status_code = 409


class InputError(ForgeError):
    status_code = 422
