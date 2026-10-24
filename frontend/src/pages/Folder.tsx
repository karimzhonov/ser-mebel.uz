import { useNavigate, useParams } from "react-router-dom";
import { FolderBrowser } from "@/components/domain";
import { Card, PageHeader } from "@/components/ui";

export default function FolderPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  return (
    <div>
      <PageHeader title="Файлы" />
      <Card>
        <FolderBrowser folderId={Number(id)} onNavigate={(next) => navigate(`/files/${next}`)} />
      </Card>
    </div>
  );
}
