/*
 * Profile-aware WebGL compatibility layer.
 *
 * The native rendering implementation remains in charge of context creation,
 * shaders, buffers, extensions, and every parameter that is not explicitly
 * present in __stealth.webglProfile.  Only the small, fingerprint-relevant
 * read surface is adapted.  This keeps WebGL libraries compatible while
 * allowing an embedding profile to describe a coherent desktop GPU.
 */
(function webglStealthModule() {
  "use strict";

  const root = typeof globalThis !== "undefined" ? globalThis : window;
  const stealth = root && root.__stealth && typeof root.__stealth === "object"
    ? root.__stealth : null;
  const configured = stealth && stealth.webglProfile &&
    typeof stealth.webglProfile === "object" ? stealth.webglProfile : null;

  // Native fallback is deliberate: without a profile this module must not
  // alter the browser's GPU behavior or introduce an artificial fingerprint.
  if (!configured || Object.keys(configured).length === 0) return;

  const hasWebGL = typeof WebGLRenderingContext !== "undefined";
  const hasWebGL2 = typeof WebGL2RenderingContext !== "undefined";
  if (!hasWebGL && !hasWebGL2) return;

  const moduleMarker = Symbol.for("cemeru.stealth.webgl.v1");
  const methodMarker = Symbol.for("cemeru.stealth.webgl.method.v1");
  const own = (object, property) =>
    Object.prototype.hasOwnProperty.call(object, property);

  function descriptor(object, property) {
    for (let owner = object; owner; owner = Reflect.getPrototypeOf(owner)) {
      const value = Object.getOwnPropertyDescriptor(owner, property);
      if (value) return { owner, value };
    }
    return null;
  }

  function validState(state) {
    return state && state.sources && typeof state.sources.set === "function" &&
      typeof state.original === "function" && typeof state.replacement === "function";
  }

  // Reuse the intrinsic masker installed by an earlier module.  The fallback
  // creates the same state shape, so the module remains standalone when used
  // without the rest of the stack.
  const toStringDescriptor = Object.getOwnPropertyDescriptor(Function.prototype, "toString");
  const shared = [
    "navigatorFunctionState", "windowFunctionState", "screenFunctionState",
    "chromeFunctionState", "permissionsFunctionState", "fontsFunctionState",
    "speechFunctionState", "performanceFunctionState",
  ].map((name) => stealth && stealth[name]).find(validState);
  const functionState = shared || (() => {
    if (!toStringDescriptor || typeof toStringDescriptor.value !== "function") return null;
    const original = toStringDescriptor.value;
    const sources = new WeakMap();
    const replacement = new Proxy(original, {
      apply(target, thisArg, args) {
        if (sources.has(thisArg)) return sources.get(thisArg);
        return Reflect.apply(target, thisArg, args);
      },
    });
    const state = { original, sources, replacement };
    try {
      Object.defineProperty(stealth, "webglFunctionState", {
        value: state, writable: false, enumerable: false, configurable: false,
      });
    } catch (_error) { /* optional state storage */ }
    return state;
  })();

  if (functionState && toStringDescriptor && toStringDescriptor.configurable &&
      toStringDescriptor.value !== functionState.replacement) {
    try {
      Object.defineProperty(Function.prototype, "toString", {
        value: functionState.replacement,
        writable: toStringDescriptor.writable,
        enumerable: toStringDescriptor.enumerable,
        configurable: toStringDescriptor.configurable,
      });
    } catch (_error) { /* hardened realms may refuse optional masking */ }
  }

  function nativeSource(value, fallback) {
    if (functionState && typeof value === "function") {
      try { return Reflect.apply(functionState.original, value, []); }
      catch (_error) { /* use fallback */ }
    }
    return fallback;
  }

  function callable(nativeFunction, implementation, name) {
    if (typeof nativeFunction !== "function") return null;
    if (!functionState) return new Proxy(nativeFunction, { apply: (_target, receiver, args) =>
      Reflect.apply(implementation, receiver, args) });
    const wrapped = new Proxy(nativeFunction, {
      apply(_target, receiver, args) {
        return Reflect.apply(implementation, receiver, args);
      },
    });
    functionState.sources.set(
      wrapped,
      nativeSource(nativeFunction, `function ${name}() { [native code] }`),
    );
    return wrapped;
  }

  function readSection(name) {
    const value = configured[name];
    return value && typeof value === "object" && !Array.isArray(value) ? value : null;
  }

  function sectionFor(receiver, fallbackName) {
    const webgl2 = hasWebGL2 && (() => {
      try { return receiver instanceof WebGL2RenderingContext; }
      catch (_error) { return false; }
    })();
    const nested = readSection(webgl2 ? "webgl2" : "webgl");
    if (nested) return nested;
    // A flat profile is accepted for embedders that only need WebGL 1 values.
    return configured;
  }

  function profileValue(section, key) {
    const aliases = {
      version: ["version"],
      shading_language_version: ["shading_language_version", "shadingLanguageVersion"],
      vendor: ["vendor"],
      renderer: ["renderer"],
      unmasked_vendor: ["unmasked_vendor", "unmaskedVendor"],
      unmasked_renderer: ["unmasked_renderer", "unmaskedRenderer"],
      max_texture_size: ["max_texture_size", "maxTextureSize"],
      max_viewport_dims: ["max_viewport_dims", "maxViewportDims"],
      max_renderbuffer_size: ["max_renderbuffer_size", "maxRenderbufferSize"],
      max_vertex_attribs: ["max_vertex_attribs", "maxVertexAttribs"],
      max_texture_image_units: ["max_texture_image_units", "maxTextureImageUnits"],
      max_combined_texture_image_units: ["max_combined_texture_image_units", "maxCombinedTextureImageUnits"],
      max_cube_map_texture_size: ["max_cube_map_texture_size", "maxCubeMapTextureSize"],
      max_vertex_texture_image_units: ["max_vertex_texture_image_units", "maxVertexTextureImageUnits"],
      max_fragment_uniform_vectors: ["max_fragment_uniform_vectors", "maxFragmentUniformVectors"],
      max_vertex_uniform_vectors: ["max_vertex_uniform_vectors", "maxVertexUniformVectors"],
      max_varying_vectors: ["max_varying_vectors", "maxVaryingVectors"],
    }[key] || [key];
    const source = section.parameters && typeof section.parameters === "object"
      ? Object.assign({}, section, section.parameters) : section;
    for (const alias of aliases) {
      if (own(source, alias) && source[alias] !== null && source[alias] !== undefined) {
        return { found: true, value: source[alias] };
      }
    }
    return { found: false, value: undefined };
  }

  const extensionParameterIds = {
    unmasked_vendor: 0x9245,
    unmasked_renderer: 0x9246,
  };

  const parameterNames = [
    "version", "shading_language_version", "vendor", "renderer",
    "unmasked_vendor", "unmasked_renderer", "max_texture_size",
    "max_viewport_dims", "max_renderbuffer_size", "max_vertex_attribs",
    "max_texture_image_units", "max_combined_texture_image_units",
    "max_cube_map_texture_size", "max_vertex_texture_image_units",
    "max_fragment_uniform_vectors", "max_vertex_uniform_vectors",
    "max_varying_vectors",
  ];

  function constantId(receiver, key) {
    const constantNames = {
      version: "VERSION",
      shading_language_version: "SHADING_LANGUAGE_VERSION",
      vendor: "VENDOR",
      renderer: "RENDERER",
      max_texture_size: "MAX_TEXTURE_SIZE",
      max_viewport_dims: "MAX_VIEWPORT_DIMS",
      max_renderbuffer_size: "MAX_RENDERBUFFER_SIZE",
      max_vertex_attribs: "MAX_VERTEX_ATTRIBS",
      max_texture_image_units: "MAX_TEXTURE_IMAGE_UNITS",
      max_combined_texture_image_units: "MAX_COMBINED_TEXTURE_IMAGE_UNITS",
      max_cube_map_texture_size: "MAX_CUBE_MAP_TEXTURE_SIZE",
      max_vertex_texture_image_units: "MAX_VERTEX_TEXTURE_IMAGE_UNITS",
      max_fragment_uniform_vectors: "MAX_FRAGMENT_UNIFORM_VECTORS",
      max_vertex_uniform_vectors: "MAX_VERTEX_UNIFORM_VECTORS",
      max_varying_vectors: "MAX_VARYING_VECTORS",
    };
    if (extensionParameterIds[key] !== undefined) return extensionParameterIds[key];
    const name = constantNames[key];
    if (!name) return undefined;
    try {
      const value = receiver[name];
      return typeof value === "number" ? value : undefined;
    } catch (_error) { return undefined; }
  }

  function keyForParameter(receiver, parameter) {
    if (typeof parameter !== "number") return null;
    for (const key of parameterNames) {
      if (constantId(receiver, key) === parameter) return key;
    }
    return null;
  }

  function copyProfileValue(profileValueValue, nativeValue, key) {
    if (Array.isArray(profileValueValue)) {
      if (ArrayBuffer.isView(nativeValue) && typeof nativeValue.constructor === "function") {
        try { return new nativeValue.constructor(profileValueValue); }
        catch (_error) { /* use a regular array below */ }
      }
      if (key === "max_viewport_dims") {
        try { return new Int32Array(profileValueValue); }
        catch (_error) { /* use a regular array below */ }
      }
      return profileValueValue.slice();
    }
    if (typeof nativeValue === "number") {
      const value = Number(profileValueValue);
      return Number.isFinite(value) ? value : nativeValue;
    }
    if (typeof nativeValue === "string") return String(profileValueValue);
    return profileValueValue;
  }

  function validReceiver(receiver, constructors) {
    for (const constructor of constructors) {
      try {
        if (receiver instanceof constructor) return true;
      } catch (_error) { /* continue */ }
    }
    return false;
  }

  function profileExtensions(section) {
    const values = section.supported_extensions || section.supportedExtensions || section.extensions;
    if (!Array.isArray(values)) return null;
    return values.filter((value, index, list) =>
      typeof value === "string" && value && list.indexOf(value) === index);
  }

  function installOnTargets(targets) {
    const constructors = targets.map((target) => target.constructor);
    const prototypes = targets.map((target) => target.prototype);
    const owners = new Set();

    for (const proto of prototypes) {
      if (!proto || proto[moduleMarker]) continue;
      try {
        Object.defineProperty(proto, moduleMarker, {
          value: true, writable: false, enumerable: false, configurable: false,
        });
      } catch (_error) { /* marker is optional */ }
    }

    function installMethod(property, implementationFactory) {
      for (const proto of prototypes) {
        const found = descriptor(proto, property);
        if (!found || !found.value || typeof found.value.value !== "function") continue;
        if (found.owner[methodMarker] && found.owner[methodMarker][property]) {
          owners.add(found.owner);
          continue;
        }
        if (found.value.configurable === false) continue;
        const original = found.value.value;
        const implementation = implementationFactory(original);
        const wrapped = callable(original, implementation, original.name || property);
        if (typeof wrapped !== "function") continue;
        try {
          Object.defineProperty(found.owner, property, {
            value: wrapped,
            writable: found.value.writable,
            enumerable: found.value.enumerable,
            configurable: found.value.configurable,
          });
          let state = found.owner[methodMarker];
          if (!state) {
            state = {};
            Object.defineProperty(found.owner, methodMarker, {
              value: state, writable: false, enumerable: false, configurable: false,
            });
          }
          state[property] = true;
          owners.add(found.owner);
        } catch (_error) { /* native descriptors may be hardened */ }
      }
    }

    installMethod("getParameter", (nativeMethod) => function getParameter(parameter) {
      if (!validReceiver(this, constructors)) throw new TypeError("Illegal invocation");
      const nativeValue = Reflect.apply(nativeMethod, this, [parameter]);
      const key = keyForParameter(this, parameter);
      if (!key) return nativeValue;
      const configuredValue = profileValue(sectionFor(this, targets[0].name), key);
      return configuredValue.found
        ? copyProfileValue(configuredValue.value, nativeValue, key)
        : nativeValue;
    });

    installMethod("getSupportedExtensions", (nativeMethod) => function getSupportedExtensions() {
      if (!validReceiver(this, constructors)) throw new TypeError("Illegal invocation");
      const nativeValue = Reflect.apply(nativeMethod, this, []);
      const configuredExtensions = profileExtensions(sectionFor(this, targets[0].name));
      return configuredExtensions ? configuredExtensions.slice() : nativeValue;
    });

    installMethod("getExtension", (nativeMethod) => function getExtension(name) {
      if (!validReceiver(this, constructors)) throw new TypeError("Illegal invocation");
      // Extension objects remain native.  In particular, debug_renderer_info
      // and anisotropic filtering are delegated unchanged when supported by
      // the browser, preserving library feature detection and rendering.
      return Reflect.apply(nativeMethod, this, [name]);
    });

    return owners;
  }

  const targets = [];
  if (hasWebGL) targets.push({ name: "webgl", constructor: WebGLRenderingContext, prototype: WebGLRenderingContext.prototype });
  if (hasWebGL2) targets.push({ name: "webgl2", constructor: WebGL2RenderingContext, prototype: WebGL2RenderingContext.prototype });
  installOnTargets(targets);
})();
