/**
 * Test environment for this app.
 *
 * Everything here exists because a unit test must not depend on a device, a
 * network, or a signed-in session. Anything mocked at this level is mocked for
 * a stated reason — a blanket mock of a module the tests then assert against is
 * a test of the mock.
 */

// React Native's animation driver warns loudly under jest and the warning is
// noise, not signal: nothing here asserts on animation.
jest.mock('react-native/Libraries/Animated/NativeAnimatedHelper', () => ({}), {
  virtual: true,
});

// NetInfo talks to the platform. `netBudget` subscribes to it at import time,
// so without this every suite that touches the API layer would hang on a native
// module that does not exist in node.
jest.mock('@react-native-community/netinfo', () => ({
  __esModule: true,
  default: {
    addEventListener: jest.fn(() => jest.fn()),
    refresh: jest.fn(() => Promise.resolve({ type: 'wifi', isConnected: true })),
    fetch: jest.fn(() => Promise.resolve({ type: 'wifi', isConnected: true })),
  },
  addEventListener: jest.fn(() => jest.fn()),
  refresh: jest.fn(() => Promise.resolve({ type: 'wifi', isConnected: true })),
}));

// `__DEV__` is a React Native global. Several modules branch on it to decide
// whether to log; under jest it is already true, but asserting it keeps a
// change to the harness from silently changing what the code does.
global.__DEV__ = true;

// Fail a test that logs an unexpected React error — a key warning or an invalid
// prop is a real defect, and swallowing it is how a render test passes while
// rendering nothing.
const originalError = console.error;
beforeAll(() => {
  console.error = (...args) => {
    const message = String(args[0] ?? '');
    if (message.includes('Warning: An update to') || message.includes('not wrapped in act')) {
      return;
    }
    originalError(...args);
  };
});
afterAll(() => {
  console.error = originalError;
});
