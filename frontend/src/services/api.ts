import { createApi, fetchBaseQuery } from "@reduxjs/toolkit/query/react";

import { API_URL } from "@/lib/config";

/** Base RTK Query API. Feature endpoints are added with api.injectEndpoints(). */
export const api = createApi({
  reducerPath: "api",
  baseQuery: fetchBaseQuery({ baseUrl: `${API_URL}/api/v1` }),
  tagTypes: ["Video", "Event"],
  endpoints: () => ({}),
});
