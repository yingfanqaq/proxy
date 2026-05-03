export {};

declare global {
  interface Window {
    electronAPI?: {
      getAutoLaunch: () => Promise<boolean>;
      setAutoLaunch: (enabled: boolean) => Promise<boolean>;
    };
  }
}
