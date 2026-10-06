import type { ApiResponse, Page, PagedResponse } from "@/types/api";
import type { Job, Video, VideoEvent } from "@/types/video";

import { api } from "./api";

const unwrap = <T>(response: ApiResponse<T>): T => response.data;
const toPage = <T>(response: PagedResponse<T>): Page<T> => ({
  items: response.data,
  pagination: response.pagination,
});

export const videosApi = api.injectEndpoints({
  endpoints: (build) => ({
    getVideos: build.query<Page<Video>, { page: number; pageSize: number }>({
      query: ({ page, pageSize }) => ({ url: "/videos", params: { page, page_size: pageSize } }),
      transformResponse: toPage<Video>,
      providesTags: (result) => [
        ...(result?.items.map((video) => ({ type: "Video" as const, id: video.id })) ?? []),
        { type: "Video", id: "LIST" },
      ],
    }),

    getVideo: build.query<Video, string>({
      query: (id) => `/videos/${id}`,
      transformResponse: unwrap<Video>,
      providesTags: (_result, _error, id) => [{ type: "Video", id }],
    }),

    processVideo: build.mutation<Job, string>({
      query: (id) => ({ url: `/videos/${id}/process`, method: "POST" }),
      transformResponse: unwrap<Job>,
      invalidatesTags: (_result, _error, id) => [
        { type: "Video", id },
        { type: "Video", id: "LIST" },
      ],
    }),

    cancelJob: build.mutation<Job, { jobId: string; videoId: string }>({
      query: ({ jobId }) => ({ url: `/jobs/${jobId}/cancel`, method: "POST" }),
      transformResponse: unwrap<Job>,
      invalidatesTags: (_result, _error, { videoId }) => [{ type: "Video", id: videoId }],
    }),

    deleteVideo: build.mutation<null, string>({
      query: (id) => ({ url: `/videos/${id}`, method: "DELETE" }),
      transformResponse: unwrap<null>,
      invalidatesTags: [{ type: "Video", id: "LIST" }],
    }),

    getEvents: build.query<
      Page<VideoEvent>,
      { jobId: string; eventType?: string; page: number; pageSize: number }
    >({
      query: ({ jobId, eventType, page, pageSize }) => ({
        url: "/events",
        params: { job_id: jobId, event_type: eventType || undefined, page, page_size: pageSize },
      }),
      transformResponse: toPage<VideoEvent>,
      providesTags: (_result, _error, { jobId }) => [{ type: "Event", id: jobId }],
    }),
  }),
});

export const {
  useGetVideosQuery,
  useGetVideoQuery,
  useProcessVideoMutation,
  useCancelJobMutation,
  useDeleteVideoMutation,
  useGetEventsQuery,
} = videosApi;
