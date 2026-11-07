"""Pure preflight compatibility; no startup, execution or transaction qualification."""

from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError

from modkit_events.contracts import ContractRegistry, EventContract
from modkit_events.persistence.errors import ErrorCode, PersistenceError
from modkit_events.persistence.models import Capability
from modkit_events.subscriptions import (
    InvalidSubscriptionConfiguration,
    Subscription,
    UnsupportedCapabilityError,
)

from modkit_workers import (
    AcquireRequest,
    HandlerKind,
    HandlerRegistration,
    HandlerRegistry,
    InvalidWorkerConfiguration,
    UnknownCommandType,
    UnsupportedHandlerVersion,
)


def forbidden_handler(context):
    raise AssertionError("Preflight executed handler")


class ForbiddenValidator:
    def validate(self, payload):
        raise AssertionError("Preflight executed payload validator")


def handlers(pairs=(("a", 1), ("b", 2)), *, route="events"):
    return HandlerRegistry(
        HandlerRegistration(
            command_type=name,
            schema_version=version,
            handler=forbidden_handler,
            kind=HandlerKind.SYNC,
            route=route,
        )
        for name, version in pairs
    )


def contracts(pairs=(("a", 1), ("b", 2)), *, route="events"):
    return ContractRegistry(
        EventContract(
            name=name, schema_version=version, route=route, validator=ForbiddenValidator()
        )
        for name, version in pairs
    )


def request(pairs=(("a", 1), ("b", 2))):
    return AcquireRequest(
        capabilities=[Capability(command_type=n, schema_version=v) for n, v in pairs],
        limit=1,
        discovery_budget=16,
    )


def subscription(*, names=("a", "b"), route="events", identity="subscriber"):
    return Subscription(subscription_id=identity, group=identity, route=route, event_names=names)


class AcquisitionPreflight(unittest.TestCase):
    def test_exact_subset_returns_fresh_canonical_snapshot(self):
        original = request((("b", 2), ("a", 1)))
        result = handlers((("a", 1), ("a", 3), ("b", 2))).validate_acquisition(original)
        self.assertIsNot(result, original)
        self.assertEqual(
            [(c.command_type, c.schema_version) for c in result.capabilities],
            [("a", 1), ("b", 2)],
        )
        self.assertIsNot(result.capabilities[0], original.capabilities[0])
        self.assertEqual((result.limit, result.discovery_budget), (1, 16))
        with self.assertRaises(FrozenInstanceError):
            result.limit = 2

    def test_unknown_unsupported_and_crossproduct_do_not_acquire(self):
        registry = handlers()
        for pairs, expected in (
            ((("unknown", 1),), UnknownCommandType),
            ((("a", 2),), UnsupportedHandlerVersion),
            ((("b", 1),), UnsupportedHandlerVersion),
        ):
            with self.subTest(pairs=pairs), self.assertRaises(expected):
                registry.validate_acquisition(request(pairs))

    def test_request_revalidation_preserves_canonical_errors(self):
        registry = handlers()
        value = request()
        object.__setattr__(value, "limit", True)
        with self.assertRaises(InvalidWorkerConfiguration):
            registry.validate_acquisition(value)
        self.assertIs(value.limit, True)
        value = request()
        object.__setattr__(value.capabilities[0], "schema_version", 2**31)
        with self.assertRaises(PersistenceError) as caught:
            registry.validate_acquisition(value)
        self.assertIs(caught.exception.code, ErrorCode.LOCAL_INVALID_ARGUMENT)
        value = request()
        object.__setattr__(value, "capabilities", [value.capabilities[0]] * 2)
        with self.assertRaises(InvalidWorkerConfiguration):
            registry.validate_acquisition(value)

    def test_caller_iterator_and_baseexception_keep_identity(self):
        class Stop(BaseException):
            pass

        for error in (RuntimeError("caller"), Stop()):
            value = request()

            def broken():
                yield Capability(command_type="a", schema_version=1)
                raise error

            object.__setattr__(value, "capabilities", broken())
            with self.assertRaises(type(error)) as caught:
                handlers().validate_acquisition(value)
            self.assertIs(caught.exception, error)

    def test_exact_input_class_and_maximum_request(self):
        class RequestSubclass(AcquireRequest):
            pass

        with self.assertRaisesRegex(InvalidWorkerConfiguration, "Expected AcquireRequest"):
            handlers().validate_acquisition(
                RequestSubclass(
                    **dict(capabilities=request().capabilities, limit=1, discovery_budget=16)
                )
            )
        pairs = tuple(("a", i) for i in range(1, 257))
        self.assertEqual(
            len(handlers(pairs).validate_acquisition(request(pairs)).capabilities), 256
        )


class SubscriptionPreflight(unittest.TestCase):
    def test_full_logical_wide_versions_with_explicit_active_subset(self):
        pairs = (("a", 1), ("a", 2**80), ("b", 2))
        original = request()
        result = handlers(pairs).validate_subscription(
            subscription(), contracts(pairs), request=original
        )
        self.assertIsNot(result, original)
        self.assertEqual(
            [(c.command_type, c.schema_version) for c in result.capabilities],
            [("a", 1), ("b", 2)],
        )
        self.assertIn(("a", 2**80), handlers(pairs).capabilities())

    def test_active_subset_must_cover_every_subscribed_name(self):
        with self.assertRaises(UnsupportedCapabilityError):
            handlers().validate_subscription(
                subscription(), contracts(), request=request((("a", 1),))
            )

    def test_full_logical_manifest_is_checked_even_for_inactive_version(self):
        with self.assertRaises(UnsupportedCapabilityError):
            handlers((("a", 1), ("a", 3), ("b", 2))).validate_subscription(
                subscription(), contracts(), request=request()
            )

    def test_worker_routes_and_shared_contract_routes_are_distinct_checks(self):
        for route in (None, "other"):
            with (
                self.subTest(route=route),
                self.assertRaisesRegex(
                    InvalidWorkerConfiguration, "Handler route does not match subscription"
                ),
            ):
                handlers(route=route).validate_subscription(
                    subscription(), contracts(), request=request()
                )
        with self.assertRaises(UnsupportedCapabilityError):
            handlers().validate_subscription(
                subscription(), contracts(route="other"), request=request()
            )
        # Jobs do not acquire an Event route requirement.
        handlers(route=None).validate_acquisition(request())

    def test_missing_and_extra_logical_names_fail_shared_manifest(self):
        with self.assertRaises(UnsupportedCapabilityError):
            handlers((("a", 1),)).validate_subscription(
                subscription(), contracts(), request=request((("a", 1),))
            )
        with self.assertRaises(UnsupportedCapabilityError):
            handlers().validate_subscription(
                subscription(names=("a",)), contracts(), request=request((("a", 1),))
            )

    def test_subscription_reconstruction_checks_public_mutation(self):
        for field, value in (
            ("event_names", []),
            ("event_names", ["a", "a"]),
            ("route", ""),
            ("subscription_id", ""),
            ("start_position", "beginning"),
        ):
            item = subscription()
            object.__setattr__(item, field, value)
            with self.subTest(field=field), self.assertRaises(InvalidSubscriptionConfiguration):
                handlers().validate_subscription(item, contracts(), request=request())
            self.assertIs(getattr(item, field), value)

    def test_exact_shared_classes_and_required_request(self):
        class SubscriptionSubclass(Subscription):
            pass

        class ContractsSubclass(ContractRegistry):
            pass

        for sub, registry in (
            (
                SubscriptionSubclass(
                    subscription_id="s", group="s", route="events", event_names=["a"]
                ),
                contracts(),
            ),
            (subscription(), ContractsSubclass([])),
            (object(), contracts()),
        ):
            with self.assertRaisesRegex(
                InvalidWorkerConfiguration, "Expected Subscription and ContractRegistry"
            ):
                handlers().validate_subscription(sub, registry, request=request())
        with self.assertRaises(TypeError):
            handlers().validate_subscription(subscription(), contracts())

    def test_independent_subscribers_have_no_global_group_state(self):
        for identity in ("one", "two"):
            handlers().validate_subscription(
                subscription(identity=identity), contracts(), request=request()
            )


class ExactReceiverPreflight(unittest.TestCase):
    def test_both_base_methods_reject_subclass_before_override_or_invalid_inputs(self):
        class OverriddenRegistry(HandlerRegistry):
            def get(self, *args):
                raise AssertionError("get override executed")

            def capabilities(self):
                raise AssertionError("capabilities override executed")

            def registrations(self):
                raise AssertionError("registrations override executed")

            def validate_acquisition(self, *args):
                raise AssertionError("acquisition override executed")

        value = OverriddenRegistry([])
        for method, args, kwargs in (
            (HandlerRegistry.validate_acquisition, (object(),), {}),
            (HandlerRegistry.validate_subscription, (object(), object()), {"request": object()}),
        ):
            with self.assertRaisesRegex(InvalidWorkerConfiguration, "Expected HandlerRegistry"):
                method(value, *args, **kwargs)


if __name__ == "__main__":
    unittest.main()
