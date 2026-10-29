import FeedsArticle from "@/components/feeds/feeds-article";

export default async function ArticlePage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  return <FeedsArticle slug={slug} />;
}
