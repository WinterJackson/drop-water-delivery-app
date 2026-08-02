import VendorApiRoutes from "@/API/routes/VendorApiRoutes";
import { retryTransientOnly } from "@/API/errors";
import { useApiRequest } from "@/API/useApiClient";
import { useInfiniteQuery } from "@tanstack/react-query";

/** Same honest envelope as `/orders` — see `VendorOrdersPage`. */
export interface VendorProductsPage {
	items: any[];
	limit: number;
	offset: number;
	has_more: boolean;
}

export function useVendorProducts(searchQuery: string = "", stockFilter: string = "All", limit: number = 20) {
	const { get } = useApiRequest();

	return useInfiniteQuery({
		queryKey: ["vendorProducts", searchQuery, stockFilter, limit],
		queryFn: ({ pageParam = 0 }) => {
			const qs = new URLSearchParams({ limit: String(limit), offset: String(pageParam) });
			if (searchQuery.trim().length > 1) qs.append("search_query", searchQuery.trim());
			if (stockFilter !== "All") qs.append("stock_filter", stockFilter);

			return get<VendorProductsPage>(`${VendorApiRoutes.GetProducts.path}?${qs.toString()}`);
		},
		initialPageParam: 0,
		getNextPageParam: (lastPage) =>
			lastPage?.has_more ? (lastPage.offset ?? 0) + (lastPage.limit ?? limit) : undefined,
		retry: retryTransientOnly(),
	});
}
