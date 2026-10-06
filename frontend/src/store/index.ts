import { configureStore } from "@reduxjs/toolkit";

import { api } from "@/services/api";

import videoReducer from "./slices/videoSlice";

/** One store per browser session; created in StoreProvider so it is never shared between
 * requests during server rendering. */
export const makeStore = () =>
  configureStore({
    reducer: {
      [api.reducerPath]: api.reducer,
      video: videoReducer,
    },
    middleware: (getDefaultMiddleware) => getDefaultMiddleware().concat(api.middleware),
  });

export type AppStore = ReturnType<typeof makeStore>;
export type RootState = ReturnType<AppStore["getState"]>;
export type AppDispatch = AppStore["dispatch"];
