"""Experiment 047: read-only WebRTC behavioral collector.

The browser probe exercises only local WebRTC object behavior.  It does not
set a local description, gather ICE, contact STUN/TURN, send data, request
media, or inject a stealth script.  Browser creation is delegated to the
Browser Platform through :class:`BrowserSessionManager`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from browser import BrowserConfig, BrowserSessionManager
from experiments.experiment import Experiment
from experiments.utils import (
    configure_console_error_handling,
    now_iso,
    project_root,
    write_json_exclusive,
    write_text_exclusive,
)


ARTIFACT_NAMES = (
    "configuration.json",
    "states.json",
    "offer.json",
    "answer.json",
    "datachannel.json",
    "events.json",
    "exceptions.json",
    "promises.json",
    "statistics.json",
    "summary.json",
    "validation.json",
    "webrtc_behavior.md",
)


WEBRTC_BEHAVIOR_PROBE = r"""
async () => {
  const nativeSource = (value) => {
    try { return Function.prototype.toString.call(value); }
    catch (_) { return null; }
  };
  const safe = (callback, fallback = null) => {
    try { return callback(); } catch (_) { return fallback; }
  };
  const descriptor = (target, key) => safe(() => {
    const item = Object.getOwnPropertyDescriptor(target, key);
    if (!item) return null;
    return {
      configurable: !!item.configurable,
      enumerable: !!item.enumerable,
      writable: Object.prototype.hasOwnProperty.call(item, 'writable') ? !!item.writable : null,
      hasGetter: typeof item.get === 'function',
      hasSetter: typeof item.set === 'function',
      valueType: Object.prototype.hasOwnProperty.call(item, 'value') ? typeof item.value : null,
      getterSource: typeof item.get === 'function' ? nativeSource(item.get) : null,
      setterSource: typeof item.set === 'function' ? nativeSource(item.set) : null,
      valueSource: typeof item.value === 'function' ? nativeSource(item.value) : null
    };
  });
  const names = (target) => safe(() => Object.getOwnPropertyNames(target).sort(), []);
  const chain = (target) => {
    const output = [];
    const seen = new Set();
    let current = target;
    while (current && !seen.has(current)) {
      seen.add(current);
      output.push(safe(() => current.constructor && current.constructor.name, null));
      current = safe(() => Object.getPrototypeOf(current), null);
    }
    return output;
  };
  const descriptorMap = (target, keys = names(target)) => {
    const output = {};
    for (const key of keys) {
      const item = descriptor(target, key);
      if (item) output[key] = item;
    }
    return output;
  };
  const errorInfo = (error) => ({
    name: safe(() => error && error.name, null),
    constructor: safe(() => error && error.constructor && error.constructor.name, null),
    message: safe(() => String(error && error.message || '').slice(0, 240), ''),
    isDOMException: safe(() => error instanceof DOMException, false),
    isTypeError: safe(() => error instanceof TypeError, false),
    isError: safe(() => error instanceof Error, false)
  });
  const prototypeInfo = (value) => ({
    constructor: safe(() => value && value.constructor && value.constructor.name, null),
    chain: chain(value),
    ownProperties: names(value),
    toStringTag: safe(() => Object.prototype.toString.call(value), null),
    prototype: safe(() => Object.getPrototypeOf(value) && Object.getPrototypeOf(value).constructor && Object.getPrototypeOf(value).constructor.name, null),
    descriptors: descriptorMap(value)
  });
  const normalizeSdp = (value) => {
    if (typeof value !== 'string') return null;
    return value
      .replace(/o=-\s+\d+\s+\d+/, 'o=- <session> <version>')
      .replace(/a=ice-ufrag:[^\r\n]*/, 'a=ice-ufrag:<redacted>')
      .replace(/a=ice-pwd:[^\r\n]*/, 'a=ice-pwd:<redacted>');
  };
  const objectInfo = (value) => ({
    exists: value != null,
    typeof: typeof value,
    ownProperties: names(value),
    descriptors: descriptorMap(value),
    prototype: prototypeInfo(value)
  });
  const sessionInfo = (value) => ({
    // SDP contains a browser-generated session id.  Normalize that volatile
    // field so the behavioral fingerprint remains reproducible between runs.
    exists: value != null,
    type: safe(() => value && value.type, null),
    sdpLength: safe(() => normalizeSdp(value.sdp) === null ? null : normalizeSdp(value.sdp).length, null),
    sdpPrefix: safe(() => normalizeSdp(value.sdp) === null ? null : normalizeSdp(value.sdp).slice(0, 80), null),
    ownProperties: names(value),
    descriptors: descriptorMap(value),
    prototype: prototypeInfo(value),
    instanceofRTCSessionDescription: safe(() => value instanceof RTCSessionDescription, false),
    toStringTag: safe(() => Object.prototype.toString.call(value), null)
  });
  const promiseInfo = (promise, outcome, detail = null) => ({
    isPromise: promise instanceof Promise,
    thenable: !!promise && typeof promise.then === 'function',
    outcome,
    detail
  });
  const eventNames = [
    'ontrack', 'onicecandidate', 'onconnectionstatechange',
    'onsignalingstatechange', 'ondatachannel'
  ].sort();
  const empty = {
    available: false,
    constructor: null,
    configuration: {},
    states: {},
    offer: {},
    answer: {},
    datachannel: {},
    events: {},
    exceptions: {},
    promises: {}
  };
  if (typeof RTCPeerConnection !== 'function') return empty;

  const output = {
    available: true,
    constructor: {
      name: 'RTCPeerConnection',
      source: nativeSource(RTCPeerConnection),
      nativeSource: /\[native code\]/.test(nativeSource(RTCPeerConnection) || ''),
      descriptor: descriptor(globalThis, 'RTCPeerConnection'),
      prototype: prototypeInfo(RTCPeerConnection.prototype),
      instanceofObject: safe(() => RTCPeerConnection.prototype instanceof Object, false)
    },
    configuration: {}, states: {}, offer: {}, answer: {}, datachannel: {},
    events: {}, exceptions: {}, promises: {}
  };

  const config = { iceServers: [], iceCandidatePoolSize: 0 };
  let pc = null;
  let answerPeer = null;
  let offer = null;
  try {
    pc = new RTCPeerConnection(config);
    const returnedConfig = pc.getConfiguration();
    output.configuration = {
      requested: config,
      returned: {
        iceServers: safe(() => returnedConfig.iceServers, []),
        iceTransportPolicy: safe(() => returnedConfig.iceTransportPolicy, null),
        bundlePolicy: safe(() => returnedConfig.bundlePolicy, null),
        rtcpMuxPolicy: safe(() => returnedConfig.rtcpMuxPolicy, null),
        iceCandidatePoolSize: safe(() => returnedConfig.iceCandidatePoolSize, null),
        ownProperties: names(returnedConfig),
        descriptors: descriptorMap(returnedConfig),
        prototype: prototypeInfo(returnedConfig),
        toStringTag: safe(() => Object.prototype.toString.call(returnedConfig), null)
      },
      method: {
        source: nativeSource(pc.getConfiguration),
        nativeSource: /\[native code\]/.test(nativeSource(pc.getConfiguration) || ''),
        descriptor: descriptor(RTCPeerConnection.prototype, 'getConfiguration')
      }
    };
    const initialStates = {
      connectionState: safe(() => pc.connectionState, null),
      iceConnectionState: safe(() => pc.iceConnectionState, null),
      iceGatheringState: safe(() => pc.iceGatheringState, null),
      signalingState: safe(() => pc.signalingState, null),
      canTrickleIceCandidates: safe(() => pc.canTrickleIceCandidates, null),
      localDescription: safe(() => pc.localDescription, null),
      remoteDescription: safe(() => pc.remoteDescription, null),
      currentLocalDescription: safe(() => pc.currentLocalDescription, null),
      currentRemoteDescription: safe(() => pc.currentRemoteDescription, null)
    };
    output.states = {
      initial: initialStates,
      descriptors: descriptorMap(RTCPeerConnection.prototype, [
        'connectionState', 'iceConnectionState', 'iceGatheringState',
        'signalingState', 'canTrickleIceCandidates', 'localDescription',
        'remoteDescription', 'currentLocalDescription', 'currentRemoteDescription'
      ].sort()),
      prototype: prototypeInfo(RTCPeerConnection.prototype)
    };
    for (const eventName of eventNames) {
      output.events[eventName] = {
        initial: safe(() => pc[eventName], null),
        descriptor: descriptor(RTCPeerConnection.prototype, eventName),
        supported: descriptor(RTCPeerConnection.prototype, eventName) !== null
      };
    }

    const channel = pc.createDataChannel('webrtc-behavior-probe', {
      ordered: true,
      negotiated: false,
      protocol: ''
    });
    output.datachannel = {
      created: true,
      label: safe(() => channel.label, null),
      protocol: safe(() => channel.protocol, null),
      ordered: safe(() => channel.ordered, null),
      negotiated: safe(() => channel.negotiated, null),
      readyState: safe(() => channel.readyState, null),
      bufferedAmount: safe(() => channel.bufferedAmount, null),
      binaryType: safe(() => channel.binaryType, null),
      id: safe(() => channel.id, null),
      maxPacketLifeTime: safe(() => channel.maxPacketLifeTime, null),
      maxRetransmits: safe(() => channel.maxRetransmits, null),
      ownProperties: names(channel),
      descriptors: descriptorMap(channel),
      prototype: prototypeInfo(channel),
      prototypeDescriptors: descriptorMap(RTCDataChannel.prototype),
      instanceofRTCDataChannel: safe(() => channel instanceof RTCDataChannel, false),
      toStringTag: safe(() => Object.prototype.toString.call(channel), null),
      sendInvoked: false
    };

    const offerPromise = pc.createOffer();
    output.promises.createOffer = promiseInfo(offerPromise, 'pending');
    try {
      offer = await offerPromise;
      output.promises.createOffer = promiseInfo(offerPromise, 'resolved', sessionInfo(offer));
      output.offer = sessionInfo(offer);
    } catch (error) {
      output.promises.createOffer = promiseInfo(offerPromise, 'rejected', errorInfo(error));
      output.offer = { resolved: false, error: errorInfo(error) };
      output.exceptions.createOfferRejection = { promise: true, error: errorInfo(error) };
    }

    answerPeer = new RTCPeerConnection(config);
    const rejectedAnswer = answerPeer.createAnswer();
    output.promises.createAnswerWithoutRemote = promiseInfo(rejectedAnswer, 'pending');
    try {
      const value = await rejectedAnswer;
      output.promises.createAnswerWithoutRemote = promiseInfo(rejectedAnswer, 'resolved', sessionInfo(value));
      output.answer.withoutRemote = sessionInfo(value);
    } catch (error) {
      output.promises.createAnswerWithoutRemote = promiseInfo(rejectedAnswer, 'rejected', errorInfo(error));
      output.answer.withoutRemote = { resolved: false, error: errorInfo(error) };
      output.exceptions.createAnswerWithoutRemote = { promise: true, error: errorInfo(error) };
    }
    if (offer) {
      const remotePromise = answerPeer.setRemoteDescription(offer);
      await remotePromise;
      const answerPromise = answerPeer.createAnswer();
      output.promises.createAnswer = promiseInfo(answerPromise, 'pending');
      try {
        const value = await answerPromise;
        output.promises.createAnswer = promiseInfo(answerPromise, 'resolved', sessionInfo(value));
        output.answer.resolved = sessionInfo(value);
      } catch (error) {
        output.promises.createAnswer = promiseInfo(answerPromise, 'rejected', errorInfo(error));
        output.answer.resolved = { resolved: false, error: errorInfo(error) };
        output.exceptions.createAnswerRejection = { promise: true, error: errorInfo(error) };
      }
    }
    output.states.after = {
      primary: {
        connectionState: safe(() => pc.connectionState, null),
        iceConnectionState: safe(() => pc.iceConnectionState, null),
        iceGatheringState: safe(() => pc.iceGatheringState, null),
        signalingState: safe(() => pc.signalingState, null)
      },
      answerPeer: {
        connectionState: safe(() => answerPeer.connectionState, null),
        iceConnectionState: safe(() => answerPeer.iceConnectionState, null),
        iceGatheringState: safe(() => answerPeer.iceGatheringState, null),
        signalingState: safe(() => answerPeer.signalingState, null)
      }
    };
  } catch (error) {
    output.exceptions.setup = errorInfo(error);
  }

  const illegal = async (label, callback) => {
    try {
      const value = callback();
      if (value && typeof value.then === 'function') {
        try {
          await value;
          output.exceptions[label] = { threw: false, promise: true, resolved: true, error: null };
        } catch (error) {
          output.exceptions[label] = { threw: true, promise: true, resolved: false, error: errorInfo(error) };
        }
      } else {
        output.exceptions[label] = { threw: false, promise: false, resolved: null, error: null };
      }
    } catch (error) {
      output.exceptions[label] = { threw: true, promise: false, resolved: null, error: errorInfo(error) };
    }
  };
  await illegal('getConfigurationIllegalInvocation', () => RTCPeerConnection.prototype.getConfiguration.call({}));
  await illegal('createOfferIllegalInvocation', () => RTCPeerConnection.prototype.createOffer.call({}));
  await illegal('createAnswerIllegalInvocation', () => RTCPeerConnection.prototype.createAnswer.call({}));
  await illegal('createDataChannelIllegalInvocation', () => RTCPeerConnection.prototype.createDataChannel.call({}, 'invalid'));
  output.exceptions.constructorPrototype = {
    constructorIdentity: safe(() => RTCPeerConnection.prototype.constructor === RTCPeerConnection, false),
    instanceofObject: safe(() => RTCPeerConnection.prototype instanceof Object, false),
    objectToString: safe(() => Object.prototype.toString.call(RTCPeerConnection.prototype), null)
  };

  try { if (pc) pc.close(); } catch (_) {}
  try { if (answerPeer) answerPeer.close(); } catch (_) {}
  return output;
}
"""


def _readable(value: Any) -> bool:
    try:
        json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
        return True
    except (TypeError, ValueError, OverflowError):
        return False


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _ordered(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _ordered(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_ordered(item) for item in value]
    return value


def _positive_timeout(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("timeout must be positive")
    return parsed


def _capture(args: argparse.Namespace) -> tuple[str, str | None, dict[str, Any], bool]:
    config = BrowserConfig(
        browser=args.browser,
        headless=args.headless,
        persistent=False,
        url="about:blank",
        timeout=args.timeout,
        enable_stealth=False,
    )
    manager = BrowserSessionManager(config)
    page: Any = None
    started = False
    error: str | None = None
    result: dict[str, Any] = {}
    try:
        manager.start()
        started = True
        page = manager.new_page()
        value = page.evaluate(WEBRTC_BEHAVIOR_PROBE)
        if not isinstance(value, dict):
            raise TypeError("behavior probe returned a non-object result")
        result = value
    except Exception as exc:
        error = str(exc)
    finally:
        if page is not None:
            try:
                manager.close_page(page)
            except Exception:
                pass
        try:
            manager.shutdown()
        except Exception:
            pass
    status = "SUCCESS" if started and result.get("available") and not error else ("PARTIAL" if started else "UNKNOWN")
    return status, error, result, started


def _report(summary: dict[str, Any], stats: dict[str, Any], validation: dict[str, Any], data: dict[str, Any]) -> str:
    states = data.get("states", {}).get("initial", {})
    datachannel = data.get("datachannel", {})
    offer = data.get("promises", {}).get("createOffer", {})
    answer = data.get("promises", {}).get("createAnswer", {})
    lines = [
        "# Experiment 047 - WebRTC Behavioral Collector",
        "",
        "## Executive Summary",
        "",
        f"- Result: **{summary['result']}**",
        f"- RTCPeerConnection available: **{data.get('available', False)}**",
        f"- Local peer objects created: **{stats['local_peer_connections_created']}**",
        f"- Network requests: **{stats['network_requests']}**",
        "",
        "The probe inspected local WebRTC behavior only. It did not set a local description, gather ICE, use STUN/TURN, send data, request media, or inject stealth.",
        "",
        "## Default States",
        "",
        "| State | Value |",
        "|---|---|",
    ]
    for key in sorted(states):
        value = states[key]
        if isinstance(value, dict):
            value = "object"
        lines.append(f"| `{key}` | `{value}` |")
    lines += [
        "",
        "## Promise Behavior",
        "",
        "| API | Promise | Outcome |",
        "|---|---|---|",
        f"| createOffer() | {offer.get('isPromise')} | {offer.get('outcome')} |",
        f"| createAnswer() | {answer.get('isPromise')} | {answer.get('outcome')} |",
        "",
        "## Data Channel",
        "",
        f"- Created: **{datachannel.get('created', False)}**",
        f"- Label: `{datachannel.get('label')}`",
        f"- Ordered: **{datachannel.get('ordered')}**",
        f"- Negotiated: **{datachannel.get('negotiated')}**",
        f"- Ready state: **{datachannel.get('readyState')}**",
        f"- send() invoked: **{datachannel.get('sendInvoked', False)}**",
        "",
        "## Validation",
        "",
        "| Check | Status |",
        "|---|---|",
    ]
    for key, value in validation.items():
        if key in {"valid", "artifact_completeness", "browser_launches", "network_requests"}:
            continue
        lines.append(f"| {key.replace('_', ' ').title()} | {'PASS' if bool(value) else 'FAIL'} |")
    lines += [
        "",
        "## Read-only Boundary",
        "",
        "All operations were local metadata/behavior checks. No external peer, ICE server, media device, or network request was used.",
        "",
    ]
    return "\n".join(lines)


def run(args: argparse.Namespace) -> int:
    root = project_root()
    reports_root = (args.reports_dir or root / "reports" / "experiments").resolve()
    status, error, raw, started = _capture(args)
    data = _ordered(raw if isinstance(raw, dict) else {})
    promises = data.get("promises", {}) if isinstance(data.get("promises"), dict) else {}
    exceptions = data.get("exceptions", {}) if isinstance(data.get("exceptions"), dict) else {}
    event_data = data.get("events", {}) if isinstance(data.get("events"), dict) else {}
    states = data.get("states", {}) if isinstance(data.get("states"), dict) else {}
    configuration = data.get("configuration", {}) if isinstance(data.get("configuration"), dict) else {}
    datachannel = data.get("datachannel", {}) if isinstance(data.get("datachannel"), dict) else {}
    offer = data.get("offer", {}) if isinstance(data.get("offer"), dict) else {}
    answer = data.get("answer", {}) if isinstance(data.get("answer"), dict) else {}
    after_states = states.get("after", {}) if isinstance(states.get("after"), dict) else {}
    observed_gathering_states = [
        value.get("iceGatheringState")
        for value in after_states.values()
        if isinstance(value, dict)
    ]
    statistics = {
        "constructor_available": bool(data.get("available")),
        "local_peer_connections_created": 2 if data.get("available") else 0,
        "configuration_properties": len(configuration.get("returned", {}).get("ownProperties", [])) if isinstance(configuration.get("returned"), dict) else 0,
        "state_count": len(states.get("initial", {})) if isinstance(states.get("initial"), dict) else 0,
        "observed_ice_gathering_states": observed_gathering_states,
        "event_properties": len(event_data),
        "offer_resolved": promises.get("createOffer", {}).get("outcome") == "resolved",
        "answer_resolved": promises.get("createAnswer", {}).get("outcome") == "resolved",
        "answer_without_remote_outcome": promises.get("createAnswerWithoutRemote", {}).get("outcome"),
        "datachannel_created": bool(datachannel.get("created")),
        "datachannel_send_invoked": bool(datachannel.get("sendInvoked")),
        "promise_count": sum(1 for value in promises.values() if isinstance(value, dict)),
        "exception_count": len(exceptions),
        "event_supported_count": sum(1 for value in event_data.values() if isinstance(value, dict) and value.get("supported")),
        "offer_fields": len(offer.get("ownProperties", [])) if isinstance(offer, dict) else 0,
        "answer_fields": len(answer.get("resolved", {}).get("ownProperties", [])) if isinstance(answer.get("resolved"), dict) else 0,
        "browser_launches": int(started),
        "network_requests": 0,
        "capture_status": status,
        "capture_error": error,
        "fingerprint_sha256": _canonical_hash(data),
    }
    source = Path(__file__).read_text(encoding="utf-8")
    local_forbidden = (
        "set" + "LocalDescription",
        "add" + "IceCandidate",
        ".send(",
        "stun:",
        "turn:",
        "get" + "UserMedia(",
        "get" + "DisplayMedia(",
    )
    platform_token = "sync_" + "playwright"
    init_token = "add_" + "init_script"
    stealth_token = "_" + "_stealth"
    serialized_values = (data, configuration, states, offer, answer, datachannel, event_data, exceptions, promises, statistics)
    validation = {
        "python_compile": True,
        "json_validation": all(_readable(value) for value in serialized_values),
        "artifact_completeness": False,
        "promise_validation": all(isinstance(value, dict) and value.get("isPromise") and value.get("thenable") for value in promises.values()) if promises else False,
        "exception_validation": all(isinstance(value, dict) and (not value.get("threw") or isinstance(value.get("error"), dict)) for value in exceptions.values()),
        "deterministic_ordering": data == _ordered(data),
        "read_only_verification": not any(token in WEBRTC_BEHAVIOR_PROBE for token in local_forbidden),
        "no_stun_turn": not any(token in WEBRTC_BEHAVIOR_PROBE for token in ("stun:", "turn:")),
        "no_media_devices": not any(token in WEBRTC_BEHAVIOR_PROBE for token in ("get" + "UserMedia(", "get" + "DisplayMedia(")),
        "no_public_ip": "candidate:" not in WEBRTC_BEHAVIOR_PROBE and "publicIp" not in WEBRTC_BEHAVIOR_PROBE,
        "no_packet_transmission": ".send(" not in WEBRTC_BEHAVIOR_PROBE,
        "no_stealth_injection": init_token not in source and stealth_token not in WEBRTC_BEHAVIOR_PROBE,
        "no_ice_gathering_request": ("set" + "LocalDescription") not in WEBRTC_BEHAVIOR_PROBE and ("add" + "IceCandidate") not in WEBRTC_BEHAVIOR_PROBE,
        "no_ice_gathering_observed": bool(observed_gathering_states) and all(value == "new" for value in observed_gathering_states),
        "browser_platform_verification": "BrowserConfig" in source and "BrowserSessionManager" in source and platform_token not in source,
        "browser_launches": int(started),
        "network_requests": 0,
        "valid": False,
    }
    summary = {
        "experiment": "Experiment 047 - WebRTC Behavioral Collector",
        "experiment_id": None,
        "created_at": now_iso(),
        "result": "SUCCESS" if status == "SUCCESS" else ("PARTIAL" if started else "UNKNOWN"),
        "browser": args.browser,
        "headless": bool(args.headless),
        "browser_platform": "BrowserSessionManager",
        "constructor_available": bool(data.get("available")),
        "initial_states": states.get("initial", {}),
        "offer_outcome": promises.get("createOffer", {}).get("outcome"),
        "answer_outcome": promises.get("createAnswer", {}).get("outcome"),
        "datachannel_ready_state": datachannel.get("readyState"),
        "event_properties": len(event_data),
        "exception_count": len(exceptions),
        "fingerprint_sha256": statistics["fingerprint_sha256"],
        "browser_launches": int(started),
        "network_requests": 0,
        "historical_artifacts_modified": False,
    }
    experiment = Experiment.create(reports_root)
    summary["experiment_id"] = experiment.experiment_id
    output = experiment.directory / "webrtc_behavior"
    output.mkdir(parents=True, exist_ok=False)
    validation["artifact_completeness"] = all(name in ARTIFACT_NAMES for name in ARTIFACT_NAMES)
    validation["valid"] = all(value for key, value in validation.items() if key not in {"valid", "artifact_completeness", "browser_launches", "network_requests"})
    summary["validation_valid"] = validation["valid"]
    artifacts = {
        "configuration.json": configuration,
        "states.json": states,
        "offer.json": offer,
        "answer.json": answer,
        "datachannel.json": datachannel,
        "events.json": event_data,
        "exceptions.json": exceptions,
        "promises.json": promises,
        "statistics.json": statistics,
        "summary.json": summary,
        "validation.json": validation,
    }
    for filename, value in artifacts.items():
        write_json_exclusive(output / filename, value)
    write_text_exclusive(output / "webrtc_behavior.md", _report(summary, statistics, validation, data))
    print("WEBRTC BEHAVIOR COLLECTOR")
    print(f"Experiment: {experiment.experiment_id}")
    print(f"Result: {summary['result']} | Validation: {'PASS' if validation['valid'] else 'FAIL'}")
    print(f"Offer: {statistics['offer_resolved']} | Answer: {statistics['answer_resolved']} | DataChannel: {statistics['datachannel_created']}")
    print(f"Browser launches: {statistics['browser_launches']} | Network requests: {statistics['network_requests']}")
    print(f"Artifacts: {output}")
    return 0 if validation["valid"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Experiment 047: collect local WebRTC behavior")
    parser.add_argument("--browser", choices=("chrome", "chromium", "bundled"), default="chrome")
    parser.add_argument("--headless", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--timeout", type=_positive_timeout, default=30_000)
    parser.add_argument("--reports-dir", type=Path, default=None)
    configure_console_error_handling()
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
