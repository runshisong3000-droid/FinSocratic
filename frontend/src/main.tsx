import React from 'react';
import ReactDOM from 'react-dom/client';
import { MantineProvider, createTheme } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import '@mantine/core/styles.css';
import '@mantine/charts/styles.css';
import '@mantine/notifications/styles.css';
import App from './App';
import './styles.css';

const theme = createTheme({
  primaryColor: 'teal',
  fontFamily: 'Inter, Segoe UI, Microsoft YaHei UI, PingFang SC, sans-serif',
  headings: { fontFamily: 'Inter, Segoe UI, Microsoft YaHei UI, PingFang SC, sans-serif', fontWeight: '700' },
  defaultRadius: 'md',
  colors: {
    teal: ['#e4f8f3', '#c9f0e6', '#a4e7d7', '#7dddc8', '#56d0b6', '#2ebfa1', '#149d82', '#0f806d', '#0a6255', '#074a42'],
  },
});

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <MantineProvider theme={theme} defaultColorScheme="light">
      <Notifications position="top-right" />
      <App />
    </MantineProvider>
  </React.StrictMode>,
);
