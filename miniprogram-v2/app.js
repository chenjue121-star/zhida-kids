const { getRuntime } = require('./services/runtime');
App({ onLaunch() { getRuntime(); } });
